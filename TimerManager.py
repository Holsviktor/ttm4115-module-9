import paho.mqtt.client as mqtt
import stmpy
import logging
from threading import Thread
import json

MQTT_BROKER = 'mqtt20.iik.ntnu.no'
MQTT_PORT = 1883

MQTT_TOPIC_INPUT = '10/command'
MQTT_TOPIC_OUTPUT = '10/answer'


class TimerLogic:
    """
    State Machine for a named timer.

    This is the support object for a state machine that models a single timer.
    """

    states = [{'name' : 'completed'}, {'name' : 'active'}]
    transitions = [
        # Initial
        {
            'source' : 'initial',
            'target' : 'active',
            'effect' : 'start'
        },
        # Timer
        {
            'trigger':'t',
            'source':'active',
            'target':'completed',
            'effect':'stop_transition'
        },
        # Report
        {
            'trigger' : 'status',
            'source'  : 'active',
            'target'  : 'active',
            'effect'  : 'report_status'
        }
    ]

    def __init__(self, name, duration, component):
        self._logger = logging.getLogger(__name__)
        self.name = name
        self.duration = duration
        self.component = component

        self.mqtt_client = mqtt.Client()
        self._logger.debug('Timer connecting to MQTT broker {} at port {}'.format(MQTT_BROKER, MQTT_PORT))
        self.mqtt_client.connect(MQTT_BROKER, MQTT_PORT)
        self.mqtt_client.subscribe(MQTT_TOPIC_OUTPUT);
        self.mqtt_client.publish(MQTT_TOPIC_OUTPUT, "HELP ME")

        self.stm = stmpy.Machine(name=name, transitions=TimerLogic.transitions, obj=self)
        driver = stmpy.Driver()
        driver.add_machine(self.stm)
        driver.start()

    def start(self):
        self.stm.start_timer('t', self.duration)
        self._logger.info(f"Timer started, {self.duration}")
    
    def stop_transition(self):
        self.mqtt_client.publish(MQTT_TOPIC_OUTPUT, f"{self.name} FINISHED ")

    def report_status(self):
        time_remaining = self.stm.get_timer('t')
        ov = ["time", time_remaining];
        msg = json.dumps(ov, indent=6);
        self.mqtt_client.publish(MQTT_TOPIC_OUTPUT, msg);

class TimerManagerComponent:
    """
    The component to manage named timers in a voice assistant.

    This component connects to an MQTT broker and listens to commands.
    To interact with the component, do the following:

    * Connect to the same broker as the component. You find the broker address
    in the value of the variable `MQTT_BROKER`.
    * Subscribe to the topic in variable `MQTT_TOPIC_OUTPUT`. On this topic, the
    component sends its answers.
    * Send the messages listed below to the topic in variable `MQTT_TOPIC_INPUT`.

        {"command": "new_timer", "name": "spaghetti", "duration":50}

        {"command": "status_all_timers"}

        {"command": "status_single_timer", "name": "spaghetti"}

    """

    def on_connect(self, client, userdata, flags, rc):
        # we just log that we are connected
        self._logger.debug('MQTT connected to {}'.format(client))

    def on_message(self, client, userdata, msg):
        """
        Processes incoming MQTT messages.

        We assume the payload of all received MQTT messages is an UTF-8 encoded
        string, which is formatted as a JSON object. The JSON object contains
        a field called `command` which identifies what the message should achieve.

        As a reaction to a received message, we can for example do the following:

        * create a new state machine instance to handle the incoming messages,
        * route the message to an existing state machine session,
        * handle the message right here,
        * throw the message away.

        """
        self._logger.debug('Incoming message to topic {}'.format(msg.topic))
        msg_parsed = json.loads(msg.payload.decode('utf-8'));

        if "command" in msg_parsed.keys():
            if "new_timer" in msg_parsed["command"]:
                print(msg_parsed["command"]);
                try:
                    t = TimerLogic(msg_parsed["name"], msg_parsed["duration"], "no component");
                    self._logger.info(f"Created new timer with name {msg_parsed['name']}")
                    self.stm_names.append(msg_parsed["name"])
                    self.stm_driver.add_machine(t.stm);
                except Exception as e:
                    self._logger.info(f"{e}");
            elif msg_parsed["command"] == "status_all_timers":
                for name in self.stm_names:
                    self._logger.debug("requesting status from timer {name}")
                    self.stm_driver.send("status", name)
            elif msg_parsed["command"] == "status_single_timer":
                if "name" in msg_parsed.keys():
                    self.stm_driver.send("status", msg_parsed["name"])
                else:
                    self._logger.error("Name not in single status message")
            else:
                self._logger.error("Command {msg_parsed['command']} not valid")
        else:
            self._logger.error("Command not in message")
        
    def __init__(self):
        """
        Start the component.

        ## Start of MQTT
        We subscribe to the topic(s) the component listens to.
        The client is available as variable `self.client` so that subscriptions
        may also be changed over time if necessary.

        The MQTT client reconnects in case of failures.

        ## State Machine driver
        We create a single state machine driver for STMPY. This should fit
        for most components. The driver is available from the variable
        `self.driver`. You can use it to send signals into specific state
        machines, for instance.

        """
        # get the logger object for the component
        self._logger = logging.getLogger(__name__)
        print('logging under name {}.'.format(__name__))
        self._logger.info('Starting Component')

        # create a new MQTT client
        self._logger.debug('Connecting to MQTT broker {} at port {}'.format(MQTT_BROKER, MQTT_PORT))
        self.mqtt_client = mqtt.Client()
        # callback methods
        self.mqtt_client.on_connect = self.on_connect
        self.mqtt_client.on_message = self.on_message
        # Connect to the broker
        self.mqtt_client.connect(MQTT_BROKER, MQTT_PORT)
        # subscribe to proper topic(s) of your choice
        self.mqtt_client.subscribe(MQTT_TOPIC_INPUT)
        # start the internal loop to process MQTT messages
        self.mqtt_client.loop_start()

        # we start the stmpy driver, without any state machines for now
        self.stm_driver = stmpy.Driver()
        self.stm_driver.start(keep_active=True)
        self._logger.debug('Component initialization finished')

        # list of all machines
        self.stm_names = []


    def stop(self):
        """
        Stop the component.
        """
        # stop the MQTT client
        self.mqtt_client.loop_stop()

        # stop the state machine Driver
        self.stm_driver.stop()


# logging.DEBUG: Most fine-grained logging, printing everything
# logging.INFO:  Only the most important informational log items
# logging.WARN:  Show only warnings and errors.
# logging.ERROR: Show only error messages.
debug_level = logging.DEBUG
logger = logging.getLogger(__name__)
logger.setLevel(debug_level)
ch = logging.StreamHandler()
ch.setLevel(debug_level)
formatter = logging.Formatter('%(asctime)s - %(name)-12s - %(levelname)-8s - %(message)s')
ch.setFormatter(formatter)
logger.addHandler(ch)

t = TimerManagerComponent()
