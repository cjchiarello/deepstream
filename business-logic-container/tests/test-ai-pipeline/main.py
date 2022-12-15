# Copyright (c) Microsoft. All rights reserved.
# Licensed under the MIT license. See LICENSE file in the project root for
# full license information.
from azure.iot.device.aio import IoTHubModuleClient
from azure.iot.device import  Message
from InferenceParser import Inferences, Inference
from TwinParser import Twin
import asyncio
import logging
import json
import sys
import signal
import threading

# parse the twin received from the controller
twin = Twin.get_instance()

# Event indicating client stop
stop_event = threading.Event()

async def trigger_recording_action(client, pipeline_name, desired_action):
    """
    Packages and sends a message for use
    by the ai-pipeline container to start
    or stop recording
    """
    if desired_action == "start_recording":
        start_recording = True
    elif desired_action == "stop_recording":
        start_recording = False

    data =  {
        "startRecording": [
            {
            "configId": pipeline_name,
            "state": start_recording
            }
        ]
    }
    iot_msg = Message(json.dumps(data))
    await client.send_message_to_output(iot_msg, "recordingOutput")

def create_client():
    """
    Create an IoTHubModuleClient and attach handlers to it for messages we receive.
    """
    client = IoTHubModuleClient.create_from_edge_environment()

    async def receive_message_handler(message):
        """
        Handler function for all messages the BLC receives.
        """
        logging.debug(f"Message received: {message.data}; Properties: {message.custom_properties}")

        # Decode the bitstream into JSON
        message_text = message.data.decode('utf-8')
        message_json = json.loads(message_text)

        # Check the endpoint of the message and respond appropriately.
        match message.input_name:
            case "inputRegionsOfInterest":
                logging.info("Received an ROI message. Discarding.")
            case "inferenceInput":
                logging.info("Received message on 'inferenceInput' endpoint. Sending RECORD.")
                inferences = Inferences(message=message_json)
                for pipeline_id in list(set(inferences.pipeline_ids)):
                    logging.info(f"{pipeline_id}: START RECORDING")
                    await trigger_recording_action(client=client, pipeline_name=pipeline_id, desired_action="start_recording")

    async def receive_twin_patch_handler(twin_patch):
        """
        Handler for module twin, in case we want to define any configurations
        by that mechanism.
        """
        logging.info(f"Twin Patch received: {twin_patch}")

        # In this example, we allow a 'start recording' event to be triggered manually by including it in
        # this container's module twin configuration.
        if "startRecording" in twin_patch:
            iot_msg = Message(json.dumps(twin_patch))
            await client.send_message_to_output(iot_msg, "recordingOutput")

    try:
        # Set handler on the client
        client.on_message_received = receive_message_handler
        client.on_twin_desired_properties_patch_received = receive_twin_patch_handler
    except Exception as e:
        # Cleanup if failure occurs
        logging.error(f"We could not set up the IoT message handlers for some reason: {e}")
        client.shutdown()
        raise

    return client

async def run_sample(client):
    # Customize this coroutine to do whatever tasks the module initiates
    while True:
        await asyncio.sleep(1000)

def main():
    # Set logging parameters
    logformat = '[%(asctime)-15s] [%(name)s] [%(levelname)s]: %(message)s'
    loghandlers = [logging.StreamHandler(sys.stdout)]
    logging.basicConfig(level=logging.INFO, format=logformat, force=True, handlers=loghandlers)

    # Here we create an IoT client, which will do most of the work for us in handlers we define.
    client = create_client()

    # Define a handler to cleanup when module is terminated by Edge
    def module_termination_handler(signal, frame):
        logging.info("IoTHubClient sample stopped by Edge")
        stop_event.set()

    # Set the Edge termination handler
    signal.signal(signal.SIGTERM, module_termination_handler)

    # Run the sample
    loop = asyncio.get_event_loop()
    try:
        # Here we run any main-loop logic we might need.
        loop.run_until_complete(run_sample(client))
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        raise
    finally:
        logging.info("Shutting down IoT Hub Client...")
        loop.run_until_complete(client.shutdown())
        loop.close()

if __name__ == "__main__":
    main()
