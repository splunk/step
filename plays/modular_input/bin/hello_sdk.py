import time
import sys
from splunklib import modularinput

class HelloInput(modularinput.Script):
    def get_scheme(self):
        scheme = modularinput.Scheme("Hello World SDK")
        scheme.description = "A simple demonstration of a modular input using the SDK"
        scheme.use_external_validation = True

        name_arg = modularinput.Argument(
            name="name_to_greet",
            data_type=modularinput.Argument.data_type_string,
            description="Name to use in greeting",
            required_on_create=True,
            title="Who to Greet"
        )
        # If the validation message uses single quotes a very cryptic error is returned: "Expecting different token"
        name_arg.validation = "validate(match('name_to_greet', '^(?![Bb]ob)'), \"We don't like Bob.\")"
        scheme.add_argument(name_arg)

        return scheme

    def stream_events(self, config, eventWriter):
        for input_name, input_item in config.inputs.iteritems():
            for i in range(1, 50):
                event = modularinput.Event()
                event.stanza = input_name
                event.data = "Hello {}".format(input_item["name_to_greet"])
                event.sourcetype = "hello_world"
                event.time = time.mktime(time.localtime())
                eventWriter.write_event(event)

    def validate_input(self, validation_definition):
        if validation_definition.parameters["name_to_greet"].upper() == "FRED":
            raise Exception("We don't talk to Fred")

if __name__ == "__main__":
    sys.exit(HelloInput().run(sys.argv))
