import sys
import requests
import json
import anydbm
import os
import time
import datetime

from splunklib import modularinput

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

class SocrataFeed(modularinput.Script):
    def get_scheme(self):
        scheme = modularinput.Scheme("Socrata Data Feed")
        scheme.description = "Retrieve events from a Socrata-run government data site"
        scheme.use_single_instance = False
        scheme.use_external_validation = False

        url_arg = modularinput.Argument("url")
        url_arg.data_type = modularinput.Argument.data_type_string
        url_arg.description = "The Socrata SODA API resource URL"
        url_arg.required_on_create = True
        scheme.add_argument(url_arg)

        date_field_arg = modularinput.Argument("date_field")
        date_field_arg.data_type = modularinput.Argument.data_type_string
        date_field_arg.description = "Date field to sort on (and index by)"
        date_field_arg.required_on_create = True
        scheme.add_argument(date_field_arg)

        default_date_arg = modularinput.Argument("default_checkpoint_date")
        default_date_arg.data_type = modularinput.Argument.data_type_string
        default_date_arg.description = "Earliest date to index (in isoformat, like 2016-01-01)"
        default_date_arg.required_on_create = True
        scheme.add_argument(default_date_arg)

        limit_arg = modularinput.Argument("limit")
        limit_arg.data_type = modularinput.Argument.data_type_number
        limit_arg.description = "Number of events to pull per request"
        limit_arg.required_on_create = False
        scheme.add_argument(url_arg)

        return scheme

    def fetch_data(self, url, date_field, date_from, limit, ew):
        if limit < 1 or limit > 10000:
            limit = 5000

        args = {
            "$where": "{} > '{}'".format(date_field, date_from),
            "$order": date_field,
            "$limit": limit
        }
        ew.log(modularinput.EventWriter.DEBUG, "Params: {}".format(json.dumps(args)))
        r = requests.get(url, params=args)
        ew.log(modularinput.EventWriter.DEBUG, "Received response: {}".format(r.content))
        data = json.loads(r.content)
        for i in data:
            yield i

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

                new_checkpoint = checkpoint_date
                ew.log(modularinput.EventWriter.INFO, "Making request to Socrata for input {} since {}".format(input_name, checkpoint_date))
                for data in self.fetch_data(url, date_field, checkpoint_date, limit, ew):
                    datestring = data[date_field]
                    dtime = datetime.datetime.strptime(datestring, "%Y-%m-%dT%H:%M:%S.%f")
                    e = modularinput.Event()
                    e.stanza = input_name
                    e.time = time.mktime(dtime.timetuple())
                    e.data = json.dumps(data)
                    ew.write_event(e)
                if new_checkpoint < datestring:
                    new_checkpoint = datestring

            encoded_checkpoint = new_checkpoint.encode('ascii', 'ignore')
            ew.log(modularinput.EventWriter.INFO, "Moving checkpoint to {}".format(encoded_checkpoint))
            cpoint.set_checkpoint(input_name, encoded_checkpoint)


if __name__ == "__main__":
    sys.exit(SocrataFeed().run(sys.argv))
