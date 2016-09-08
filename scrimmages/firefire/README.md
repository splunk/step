# Introduction

For this exercise, let's play around a bit with modular inputs and the new
custom visualization capability that was added in Splunk 6.4.

The city of Seattle (and many other cities) have started putting their data
online, and in some cases it's pretty interesting data. Let's make use of their
API to retrieve incident response data from the Seattle Fire Department and
visualize it on a map using a heatmap.

## Plays we are practicing

-   Modular Input
-   Modular Visualization

## External technologies

-   [Leaflet](http://leafletjs.com/)
-   [Leaflet.heat](https://github.com/Leaflet/Leaflet.heat)
-   [D3](http://d3js.org)

# Getting the Data

We start, as we often do, with getting the data into Splunk. In this case, we
want to pull the data from a web service. Seattle's data portal is hosted by a
company named[ Socrata](https://www.socrata.com/). Socrata offers several ways to obtain the data they
serve- we are going to choose their SODA API.

When pulling data into Splunk we need to take a few things into consideration.
In this case the data is presented as a web service where we will need to
periodically poll for new data. Most services don't supply a cursor, so we will
have to figure out a suitable way to determine how to ask for only new data- we
don't want to add multiple copies of the same event into our indexes.

The simplest and most straightforward way is to poll every $ x $ minutes and ask
for the last $ x $ minutes of data. The problem is that this opens us up to a
couple kinds of failures. If our scheduler isn't precise, we may start early and
duplicate data. If we start late we miss data. Worst, there's no way to know if
this happens! If the Splunk indexer we are running on is down for maintenance 
or for this project you close your laptop and go home for the night, our input
won't know where to restart.

Another way is to keep track of the last item we saw, and start there on the next
polling cycle. That means that we need some way to keep track of where we are in
the list between invocations.  In our data set we have an incident date- let's use
that.  We can request all events and keep track of the time of the last one.  When
we next make a request we will use that date as a minimum filter.  This scheme
still isn't perfect- if data is added retroactively we will never see it.  There's
also a possibility that if two events have the same time we will get the first one
but skip the second if they split between our fetches. But for this case, both of 
those seem to be pretty reasonable tradeoffs.

## Configuration for the input<a id="orgheadline4"></a>

Since we are generally just pulling data in from Socrata's SODA API, we might as
well make an input that works for any SODA endpoint. In order to do that, we
need to be able to configure our inputs. In our case, we know that we will need
a resource URL, a poll interval, and a limit of items to pull per poll. We have
also decided to order by a date field for checkpointing, so we will need to know
which field in the data to use for that purpose. Finally, we will want to
backfill so that we have some data to work with right away, so let's add a field
to specify how far back to pull data from.

In Splunk we define modular inputs in a file named `README/inputs.conf.spec`.
Files with the extension `.conf.spec` tell Splunk how to parse and validate
`.conf` files. They layer just like Splunk's conf files do. In this case, we are
defining a new type of input, which we will then specify in `inputs.conf`.

Our configuration looks like this:

    [socrata_feed://<name>]
    * Pulls data from a Socrata (data.sfgov.org, data.seattle.gov) data feed
    
    url = <value>
    date_field = <value>
    default_checkpoint_date = <value>
    limit = <value>

When we define an input, we use that stanza as a template- for example, here's
the stanza we will use to bring in response data from the Seattle Fire Department<sup><a id="fnr.1" class="footref" href="#fn.1">1</a></sup>:

    [socrata_feed://seattle_fire_response]
    date_field = datetime
    default_checkpoint_date = 2016-03-01
    interval = 60
    limit = 500
    url = https://data.seattle.gov/resource/grwu-wqtk.json

That's enough for us- now we can specify several inputs if we want, and we have
everything we need to pull the data. It's probably not enough for someone who
hasn't been following along with us, however- we need to be able to supply a bit 
more detail on what we mean by 'date<sub>field</sub>', and limit.  Let's take care of that
now while it's fresh.

## Coding the input<a id="orgheadline5"></a>

Modular input scripts run in three different modes- a schema mode, a validation
mode, and a run mode. The schema mode allows us to offer our end users a more
hospitable environment for specifying the values that we need to retrieve data.
For this scrimmage we are going to be using the [Splunk Python SDK](http://dev.splunk.com/python), which gives
us an easy structure for implementing all of these modes. It's pretty simple to
do this in any language- you may just need to handle the command-line parsing
and XML yourself.

When using the Python SDK, we create a subclass of
`splunklib.modularinput.Script` and override methods corresponding to the
different stages. To specify more detail on the values we expect, let's start by
overriding the `get_scheme` method.

Splunk looks for a modular input script to have a name matching 

    from splunklib import modularinput
    class SocrataFeed(modularinput.Script):
        def get_scheme(self):
            scheme = Scheme("Socrata Data Feed")
            scheme.description = "Retrieve events from a Socrata-run government data site"
            scheme.use_single_instance = False
            scheme.use_external_validation = False
    
            url_arg = Argument("url")
            url_arg.data_type = Argument.data_type_string
            url_arg.description = "The Socrata SODA API resource URL"
            url_arg.required_on_create = True
            scheme.add_argument(url_arg)
    
            return scheme

Each arg (in this case `url`) gets the same treatment- we specify a data type, a
description, and whether or not the argument is required when the input is
created. With this information, Splunk can provide an informative GUI for
creating new inputs.

Next we need to figure out checkpointing, since that's a core piece of our
design. When our script is run to pull data the `stream_events` method will
be called with two arguments- a `config` object and an `EventWriter`. Each
app is allocated a working directory- we are given the location of that 
directory in `config.metadata["checkpoint_dir"]`.

Since we just have a directory, let's build a quick class to abstract
serializing our checkpoints, remembering that there may well be multiple
inputs to save checkpoints for. With that in mind, let's build for Python's
`with` statement and save our data in a dbm file.

    class CheckpointDB:
        def __init__(self, dir, file="checkpoints.db"):
            self.filename = os.path.join(dir, file)
    
        def __enter__(self):
            self.db = anydbm.open(self.filename, "c")
            return self
    
        def __exit__(self, type, value, traceback):
            self.db.close()
    
        def get_checkpoint(self, key, default):
            if self.db.has_key(key):
                return self.db[key]
            else:
                return default
    
        def set_checkpoint(self, key, new_checkpoint):
            self.db[key] = new_checkpoint

Now that we have that in place, it's time to actually fetch data. Start by
overriding the `stream_events` method.

    def stream_events(self, config, ew):
        # Splunk Enterprise calls the modular input, 
        # streams XML describing the inputs to stdin,
        # and waits for XML on stdout describing events.
        with CheckpointDB(config.metadata["checkpoint_dir"]) as cpoint:
            for input_name, input_item in config.inputs.iteritems():
                default_date = input_item["default_checkpoint_date"]
                url = input_item["url"]
                date_field = input_item["date_field"]
                limit = input_item["limit"]
                checkpoint_date = cpoint.get_checkpoint(input_name, default_date)
    
                new_checkpoint = None
                ew.log(EventWriter.INFO, "Making request to Socrata for input {} since {}".format(input_name, checkpoint_date))

We have a few things to point out here. First, we are using our `CheckpointDB`
class in that first statement- now we have an object that we can get and set
values on, knowing that they will be persisted even if Splunk restarts.

Next, we may get multiple inputs to fetch all at once- we specify whether or not
we get multiple inputs in one instantiation with `scheme.use_single_instance`
when we override `get_scheme`, but it's always going to show up as a dictionary
in `config.inputs` whether we get one or many.

Next we pull values from `input_item`- these are the arguments we put
definitions for in `inputs.conf.spec` and specified values for in 
`inputs.conf` (or supplied in the Splunk UI).

Finally we make a log entry for debugging, giving us information on how our
script is running. Using `EventWriter.log` means that your logging statements
will be ingested by Splunk too- look in `_internal` index under the
`splunkd.log` source. By default log levels under `EventWriter.INFO` will be
discarded.

Starting from where we left off in the listing above:

    for data in self.fetch_data(url, date_field, checkpoint_date, limit, ew):
        datestring = data[date_field]
        dtime = datetime.datetime.strptime(datestring, "%Y-%m-%dT%H:%M:%S.%f")
        e = Event()
        e.stanza = input_name
        e.time = time.mktime(dtime.timetuple())
        e.data = json.dumps(data)
        ew.write_event(e)
    if new_checkpoint < datestring:
        new_checkpoint = datestring

Here we fetch a window of data, and for each element build events.  We have 
Put the actual fetch into it's own method, and we will get to it soon.

We start with pulling the date- remember, `date_field` contains the name of the
date as specified in the input. We pull that field, parse it from Socrata's date
format into a Python `datetime` and from there into a `time` object to be set on
our new event.

Next we set the `stanza` on the `Event`. This corresponds to the `source` in
Splunk. Then we serialize the whole object into JSON and set it as the `data`
attribute.  Splunk handles JSON data extraordinarily well, using keys as event
attributes- it even handles nested keys well, so JSON is a great choice for 
an event format.

Finally we write the event (under the covers it's just getting written to 
`STDOUT`), and if the `datestring` on this event is greater than the date in 
our `new_checkpoint` object, we set `new_checkpoint` to that date.  

When we finish looping we set the new checkpoint in `cpoint`.

    encoded_checkpoint = new_checkpoint.encode('ascii', 'ignore')
    ew.log(EventWriter.INFO, "Moving checkpoint to {}".format(encoded_checkpoint))
    cpoint.set_checkpoint(input_name, encoded_checkpoint)

The actual data fetch is pretty straightforward:

    def fetch_data(self, url, date_field, date_from, limit, ew):
        if limit < 1 or limit > 10000:
            limit = 5000
    
        args = {
            "$where": "{} > '{}'".format(date_field, date_from),
            "$order": date_field,
            "$limit": limit
        }
        ew.log(EventWriter.DEBUG, "Params: {}".format(json.dumps(args)))
        r = requests.get(url, params=args)
        ew.log(EventWriter.DEBUG, "Received response: {}".format(r.content))
        data = json.loads(r.content)
        for i in data:
            yield i

This is just formatting the URL, making a request using `requests.get`, and then
parsing the response with `json.loads`, yielding each object.

## Validating the data<a id="orgheadline6"></a>

With that, we should be able to get data from Socrata. Let's play around with it 
a little bit.

# Making the Map<a id="orgheadline20"></a>

Now that we have data flowing, it's time to take a look at our visualization.
There are two visualizations known as 'heatmaps'.  The first is a matrix plot
that uses color to encode the correspondence of two categorical variables. This 
type of heatmap is a native visualization as of Splunk 6.4.  

The type of heatmap we want to play with is a map type where the geographic
frequency of an event is highlighted in color. The [Leaflet](http://leafletjs.com/) mapping library has
a heatmap plugin named [Leaflet.heat](https://github.com/Leaflet/Leaflet.heat)- we will use that.  

## Registering the visualization with Splunk<a id="orgheadline8"></a>

Our first step is telling Splunk that we have a new visualization. We do this
in visualizations.conf:

\#+INCLUDE code python ./firefire/default/visualizations.conf

The name of the stanza is going to point to where we place files for our
visualization. In our case, Splunk will look in
`appserver/static/visualizations/geoheatmap`. Specifically it's going to
load two files in that directory- `visualization.js` and `visualization.css`.

## Getting the libraries we need<a id="orgheadline9"></a>

The template in the [Custom Visualization Tutorial](http://docs.splunk.com/Documentation/Splunk/6.4.0/AdvancedDev/CustomVizTutorial) sets up a great build 
system to use for your visualization.  It uses both [npm](https://www.npmjs.com/) and [webpack](https://webpack.github.io/)- 
npm to obtain the libraries to use, and webpack to compile it all into
a single library that can be loaded when the visualization is to be 
rendered.

First, let's specify our dependencies.  In `package.json`, add leaflet 
and leaflet.heat to the `dependencies` section.

    "dependencies": {
      "jquery": "^2.2.0",
      "underscore": "^1.8.3",
      "leaflet": "1.0.0-rc.1",
      "leaflet.heat": "^0.2.0"
    }

Next, we need to do a bit of configuration for webpack.  Leaflet.heat 
expects the global variable `L` to be defined by Leaflet, and installs
itself there.  Since we are going to be using require.js, we need to
let webpack know how to handle this.

In the `module.exports` structure we add the following:

    module: {
        loaders: [
            {
                test: /leaflet\.heat\.js$/,
                loader: 'imports-loader?L=leaflet'
            }
        ]
    },

This configures a dependency for the leaflet.heat library on leaflet, 
and sets `L` up to be the leaflet library as expected.

At this point we should be able to run `npm install` at the command
line, then `npm build` to compile all of the files in the `src` 
subdirectory into a `visualization.js`.

## Configuring Splunk for visualization development<a id="orgheadline10"></a>

Before we get too far into the code for the visualization, let's set Splunk
up to make it easy to see changes as we make them. We want to change `web.conf`,
so we put the following into `${SPLUNK_HOME}/etc/system/local`:

\#+INCLUDE example ./splunk-etc/system/local/web.conf

These settings disable minification of the Javascript code (so we can read and
debug) and disable caching so that we see our changes as soon as we reload our
browsers.  Both make working in Javascript in Splunk <span class="underline">much</span> easier.

## Including css<a id="orgheadline11"></a>

Next we need to add Leaflet's CSS to our visualization.

## Setting up the visualization object<a id="orgheadline12"></a>

Now that we have our build system set up and libraries installed, we need to pull 
the libraries into our visualization's context using `require.js`.

    define([
        'jquery',
        'underscore',
        'vizapi/SplunkVisualizationBase',
        'vizapi/SplunkVisualizationUtils',
        'leaflet',
        'leaflet.heat'
        ],
        function(
            $,
            _,
            SplunkVisualizationBase,
            vizUtils,
            L,
            leaflet_heat
        ) {
    })

We request access to leaflet and leaflet.heat in the first argument to `define`.
The second argument is a function- each argument to the function corresponds to 
a requested library in the first argument list.  We don't use `leaflet_heat` 
directly- it gets added to the `L` argument using the webpack configuration we
created above.

Now that we have a context, we can build our visualization.  As with the modular
input, visualizations are specified with a Template Method design pattern- we 
override an object and implement methods that correspond to steps in a process.

    return SplunkVisualizationBase.extend({
        initialize: function() {
            SplunkVisualizationBase.prototype.initialize.apply(this, arguments);
            this.$el = $(this.el);
            this.$el.html("");
            this.$el.addClass("geoheatmap");
        },

We start with overriding the `initialize` method. Calling
`prototype.initialize.apply` ensures that all superclass initialization happens
(always a good practice).  We then create a jQuery selection of our visualization's
DOM node.  We then clear whatever is in that node's contents, and add a class that
we can use for CSS selections.

## Shaping the Data<a id="orgheadline13"></a>

Next let's override the `formatData` method and use it to transform search results
into a form that will be easy to feed into `leaflet.heat`.

    formatData: function(data) {
        var fields = {};
        for (var i=0; i<data.fields.length; i++) {
            fields[data.fields[i].name] = i;
        }
        var points = data.rows.map(function(d) {
            var lat = parseFloat(d[fields['latitude']]);
            var lon = parseFloat(d[fields['longitude']]);
            return [lat, lon, 1];
        });
        return points.filter(function(d) {return d[0] && d[1];});
    },

This method gets called whenever search data arrives- it may come in multiple
times as preview results arrive or the user changes her search.

Reading the [documentation](https://github.com/Leaflet/Leaflet.heat/blob/gh-pages/README.md) for leaflet.heat, `setLatLngs` appears to be the
most appropriate call to add points to the heatmap layer.  That call takes
a list of three-element lists- a latitude, a longitude and an intensity.

We want the intensity to be equal for each point, so we can hard-code that
value. To supply the format we need, we can simply map through the data supplied
to `formatData` by the search and return a list in the proper format. Finally we
filter on the data, ensuring that we have a latitude and longitude for each 
data point- it's possible that the data is missing or malformed for some events.

## Adding the map<a id="orgheadline14"></a>

Next we render the map.  We do this by overriding the `updateView` method.

    updateView: function(data, config) {
        var basemap_url = 'http://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png';
        var attribution = '&copy; <a href="http://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors, &copy; <a href="https://cartodb.com/attributions">CartoDB</a>';
        if (!this.map) {
            this.map = L.map(this.el).setView([47.71, -122.35], 12);
        }
        if (!this.tileLayer) {
            this.tileLayer = L.tileLayer(basemap_url, {
                attribution: attribution,
                maxZoom: 18
            }).addTo(this.map);
        }

If the map doesn't exist, create it with `L.map`, and set the viewport. We also
need a basemap, so add a `tileLayer`- we are using CartoDB's 'positron' tileset
to start with.

## Adding blobs<a id="orgheadline15"></a>

Next let's add the heatmap layer.

    if (!this.heatLayer) {
        this.heatLayer = L.heatLayer([]);
        this.map.addLayer(this.heatLayer);
    }
    this.heatLayer.setLatLngs(data);

Again, `updateView` may be called multiple times as results come in and the
search is changed, so we want to ensure that we only add the heatLayer the 
first time the method is run.  We then call `setLatLngs` on the heatmap layer
every time we get new data.

## Resizing the view<a id="orgheadline16"></a>

Now we are building the view, but we have one more override to take care of- we
need to handle resizing events. Happily this is pretty easy.

    reflow: function() {
        this.map.invalidateSize(false);
    }

The Splunk UI will call `reflow` any time the viewport changes, so we can
isolate all of our resizing logic here. For Leaflet, this is really easy- 
we just need to call `invalidateSize` on the map.  The `false` argument is
simply to tell Leaflet that we don't want to animate the sizing.

## Customizing the map<a id="orgheadline17"></a>

Our heatmap should now display. Try it out by running a search- [try](http://localhost:18000/en-US/app/firefire/search?q=search%2520source%253D%2522socrata_feed%253A%252F%252Fseattle_fire_response%2522%2520%257C%2520table%2520latitude%252C%2520longitude&display.page.search.mode=smart&dispatch.sample_ratio=1&earliest=-7d%2540h&latest=now&display.page.search.tab=visualizations&display.general.type=visualizations&display.visualizations.type=custom&display.visualizations.custom.type=firefire.geoheatmap&display.visualizations.custom.height=767&sid=1462909528.21)
`source="socrata_feed://seattle_fire_response" | table latitude, longitude`
with the 'Last 7 days' selected in the time picker.

Now we have a heatmap working. This is probably good enough for an internal app,
but heatmaps are very sensitive to the amount of data they are displaying. Too
much data and you get only the maximum color levels. Too little and the
visualization isn't visible above the base map.

To allow users of our visualization to set these properties, let's create a 
'Format' menu for our visualization.  We do this using an HTML file named
`formatter.html` in the visualization directory.

    <form class="splunk-formatter-section" section-label="Heatmap">
        <div class="control-group">
            <label class="control-label">Minimum Opacity</label>
            <splunk-text-input name="display.visualizations.custom.firefire.geoheatmap.minOpacity" value="0.1"></splunk-text-input>
            <span class="help-block">Opacity of each circle drawn (one per point)</span>
        </div>
        <div class="control-group">
            <label class="control-label">Radius</label>
            <splunk-text-input name="display.visualizations.custom.firefire.geoheatmap.radius" value="25"></splunk-text-input>
            <span class="help-block">In pixels</span>
        </div>
        <div class="control-group">
            <label class="control-label">Blur</label>
            <splunk-text-input name="display.visualizations.custom.firefire.geoheatmap.blur value="15"></splunk-text-input>
            <span class="help-block">In pixels</span>
        </div>
    </form>

The values of each of these settings are going to be supplied as keys in the
`config` argument to `updateView`.  It's a best practice to namespace your 
arguments to ensure that you don't conflict with any existing (or future!)
visualizations. 

## Add a screenshot and an example search<a id="orgheadline18"></a>

## Making the visualization available to other apps<a id="orgheadline19"></a>

# Checklist<a id="orgheadline21"></a>

-   [ ] Ensure that I document calling invalidateSize on reflow and that a reflow happens on the initial render.
-   [ ] Add link for heatmap

# Todos<a id="orgheadline28"></a>

## TODO Make notes on how to change log level      <span class="timestamp-wrapper"><span class="timestamp">&lt;2016-05-05 Thu 10:16&gt;</span></span><a id="orgheadline22"></a>

Link: <file:///Users/dponcelow/splunks/firefire/project-notes.md>

## TODO figure out source/input naming      <span class="timestamp-wrapper"><span class="timestamp">&lt;2016-05-05 Thu 10:32&gt;</span></span><a id="orgheadline23"></a>

Need to see if the default is the name of the input, or I'm setting it here.

Link: <file:///Users/dponcelow/splunks/firefire/project-notes.md>

## TODO Sort out my error handling here.      <span class="timestamp-wrapper"><span class="timestamp">&lt;2016-05-05 Thu 10:53&gt;</span></span><a id="orgheadline24"></a>

I can checkpoint after every event (original code) and call out that it will
restart at that date with the next call, or I can call out
different error handling.

Link: <file:///Users/dponcelow/splunks/firefire/project-notes.md>

## TODO Move limit < 1&#x2026; to validation      <span class="timestamp-wrapper"><span class="timestamp">&lt;2016-05-05 Thu 10:57&gt;</span></span><a id="orgheadline25"></a>

Link: <file:///Users/dponcelow/splunks/firefire/project-notes.md>

## TODO Example queries.      <span class="timestamp-wrapper"><span class="timestamp">&lt;2016-05-05 Thu 11:05&gt;</span></span><a id="orgheadline26"></a>

Link: <file:///Users/dponcelow/splunks/firefire/project-notes.md>

## TODO Figure out if contrib/css is the best approach.      <span class="timestamp-wrapper"><span class="timestamp">&lt;2016-05-05 Thu 14:37&gt;</span></span><a id="orgheadline27"></a>

Link: <file:///Users/dponcelow/splunks/firefire/project-notes.md>

<div id="footnotes">
<h2 class="footnotes">Footnotes: </h2>
<div id="text-footnotes">

<div class="footdef"><sup><a id="fn.1" class="footnum" href="#fnr.1">1</a></sup> <div class="footpara">Note that in the example application we have placed this file in `local/inputs.conf` rather than
`default/inputs.conf` as it's not something that we would distribute as part of our app.</div></div>


</div>
</div>
