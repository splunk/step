/*
 * Visualization source
 */
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
    // Extend from SplunkVisualizationBase
        var prefix = 'display.visualizations.custom.firefire.geoheatmap.';
        var tileLayers = {
            positron: {
                name: 'CartoDB Positron',
                url: 'http://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png',
                attribution: '&copy; <a href="http://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors, &copy; <a href="https://cartodb.com/attributions">CartoDB</a>'
            },
            dark_matter: {
                name: 'CartoDB Dark Matter',
                url: 'http://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png',
                attribution: '&copy; <a href="http://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors, &copy; <a href="https://cartodb.com/attributions">CartoDB</a>'
            },
            toner: {
                name: 'Stamen Toner',
                url: 'http://tile.stamen.com/toner/{z}/{x}/{y}.png',
                attribution: 'Map tiles by <a href="http://stamen.com">Stamen Design</a>, under <a href="http://creativecommons.org/licenses/by/3.0">CC BY 3.0</a>. Data by <a href="http://openstreetmap.org">OpenStreetMap</a>, under <a href="http://www.openstreetmap.org/copyright">ODbL</a>.'
            },
            watercolor: {
                name: 'Stamen Watercolor',
                url: 'http://tile.stamen.com/watercolor/{z}/{x}/{y}.png',
                attribution: 'Map tiles by <a href="http://stamen.com">Stamen Design</a>, under <a href="http://creativecommons.org/licenses/by/3.0">CC BY 3.0</a>. Data by <a href="http://openstreetmap.org">OpenStreetMap</a>, under <a href="http://creativecommons.org/licenses/by-sa/3.0">CC BY SA</a>.'
            },
        };
    return SplunkVisualizationBase.extend({
        initialize: function() {
            SplunkVisualizationBase.prototype.initialize.apply(this, arguments);
            this.$el = $(this.el);
            this.$el.html("");
            this.$el.addClass("geoheatmap");
        },

        // Optionally implement to format data returned from search.
        // The returned object will be passed to updateView as 'data'
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

        // Implement updateView to render a visualization.
        //  'data' will be the data object returned from formatData or from the search
        //  'config' will be the configuration property object
        _heatmapConfig: function(config) {
            var conf = {
                minOpacity: parseFloat(config[prefix + 'minOpacity']) || 0.2,
                radius: parseFloat(config[prefix + 'radius']) || 25,
                blur: parseFloat(config[prefix + 'blur']) || 15,
                // gradient: JSON.parse(config[prefix + 'gradient'] || "{0.4: 'blue', 0.65: 'lime', 1: 'red'}")
            };
            var color1 = config[prefix + 'color1'] || 'blue';
            var stop1 = parseFloat(config[prefix + 'colorstop1'] || 0.4);
            var color2 = config[prefix + 'color2'] || 'lime';
            var stop2 = parseFloat(config[prefix + 'colorstop2'] || 0.65);
            var color3 = config[prefix + 'color3'] || 'red';
            var stop3 = parseFloat(config[prefix + 'colorstop3']) || 1;
            conf['gradient'] = {};
            conf['gradient'][stop1] = color1;
            conf['gradient'][stop2] = color2;
            conf['gradient'][stop3] = color3;
            return conf;
        },
        updateView: function(data, config) {
            var requested_basemap = config[prefix + 'basemap_design'] || 'positron';
            if (data.length == 0) return;
            if (!this.map) {
                this.map = L.map(this.el).setView([47.71, -122.35], 12);
            // } else {
            //     this.map.invalidateSize(false);
            }
            if (!this.tileLayer || requested_basemap != this.current_basemap) {
                if (this.tileLayer) {
                    this.map.removeLayer(this.tileLayer);
                }
                this.tileLayer = L.tileLayer(tileLayers[requested_basemap].url, {
                    attribution: tileLayers[requested_basemap].attribution,
                    maxZoom: 18
                }).addTo(this.map);
                this.current_basemap = requested_basemap;
            }
            if (data.length == 0) {return;}
            if (!this.heatLayer) {
                this.heatLayer = L.heatLayer([]);
                this.map.addLayer(this.heatLayer);
            }
            this.heatLayer.setOptions(this._heatmapConfig(config));
            this.heatLayer.setLatLngs(data);
        },

        // Search data params
        getInitialDataParams: function() {
            return ({
                outputMode: SplunkVisualizationBase.ROW_MAJOR_OUTPUT_MODE,
                count: 100000
            });
        },

        // Override to respond to re-sizing events
        reflow: function() {
            if (this.map) {
                this.map.invalidateSize(false);
            }
        }
    });
});
