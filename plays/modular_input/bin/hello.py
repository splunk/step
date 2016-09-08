#!/usr/bin/env python

import sys
import logging
import time
# In this example we output raw XML strings, which isn't usually a good
# idea- using an XML library will help catch embedded entities, ensure
# that the structure remains sound, and should protect from malicious input.
# It's not as obvious what the structure looks like though, so we use
# strings to be more clear about what's going on. We do parse with a library,
# however- again, for the purpose of clarity.
import xml.etree.ElementTree as ET

logging.root.setLevel(logging.DEBUG)
# The following format allows for finding log entries related to this
# particular input. It's not of a lot of utility here, but it can be
# a handy technique.

# SPL: index=_internal sourcetype=splunkd input=HelloInput
formatter = logging.Formatter('%(levelname)s input=HelloInput %(message)s')
handler = logging.StreamHandler(stream=sys.stderr)
handler.setFormatter(formatter)
logging.root.addHandler(handler)

# Here is our scheme.  In general, schemes are static, and in fact Splunk
# will read the scheme once from an input and cache it- so if you change
# your scheme during development, you will need to restart Splunk (or
# disable and re-enable the input) in order for your changes to take effect.
#
# In this case we have created a validation to ensure that 'Bob' is not
# specified as the name to greet.  This is one of three ways to validate
# your inputs.  While simple, there are only a few ways in which you can
# validate here.  Validating in custom UI gives quicker feedback but only
# validates when adding an input through the Splunk GUI.  The final method
# is illustrated in the 'validate' method below in which we ensure that
# Fred cannot be added as a name to greet.
#
# Note the opportunities to document your parameters here- these are a
# a great opportunity to document your app's requirements to the user
# as they set up an input.
scheme = """
<scheme>
    <title>Hello World</title>
    <description>Greet the World (or someone in it)</description>
    <use_external_validation>true</use_external_validation>
    <streaming_mode>xml</streaming_mode>

    <endpoint>
        <args>
            <arg name="name_to_greet">
                <validation>
                    validate(match('name_to_greet', '^(?![Bb]ob)'), "We don't like Bob.")
                </validation>
                <title>Name to use in greeting</title>
                <description>A name.  If not supplied, 'World' will be used.</description>
            </arg>
        </args>
    </endpoint>
</scheme>
"""

def run():
    try:
        root = ET.parse(sys.stdin).getroot()
        stanza_nodes = root.findall('.//stanza')
        for stanza in stanza_nodes:
            logging.info("Starting stanza %s", stanza.attrib["name"])
            params = dict()
            print "<stream>"
            for param_node in stanza.findall('param'):
                params[param_node.attrib["name"]] = param_node.text
                for i in range(1, 50):
                    eventtime = time.mktime(time.localtime())
                    print """
                    <event>
                        <sourcetype>hello_world</sourcetype>
                        <data>Hello, {}</data>
                        <time>{}</time>
                    </event>
                    """.format(i, params.get("name_to_greet", "World"), eventtime)
                    time.sleep(1)
            print "</stream>"
    except:
        # Logging can be very handy in troubleshooting a modular input
        # SPL: index=_internal ModularInput
        logging.exception("Error while generating hello events")

def validate():
    logging.info("Validating")
    root = ET.parse(sys.stdin).getroot()
    # Note that it's item[name="x"] not stanza[name="x"]
    name = root.find(".//item/param[@name='name_to_greet']").text
    if name.upper() == "FRED":
        print """
        <error>
            <message>We don't talk to Fred</message>
        </error>"""
        sys.exit(1)

if len(sys.argv) == 1:
    run()
elif sys.argv[1].lower() == "--scheme":
    print scheme
elif sys.argv[1].lower() == "--validate-arguments":
    validate()
else:
    raise ValueError("Unknown execution mode")



