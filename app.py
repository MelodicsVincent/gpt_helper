import os
import json
import requests
import logging
import base64
from slack_bolt import App, Say
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_bolt.adapter.aws_lambda import SlackRequestHandler

# Use config_secrets_manager or config_ssm to switch between Secrets Manager or SSM
from utils import config_secrets_manager as config

# Channel IDs
id_gpt_helper_demo = 'C054CSCDPCG'
id_engineering_off_topic = 'C01CK9GUT2Q'
allowlist_channel_ids = [id_gpt_helper_demo, id_engineering_off_topic]

codachat_app_id = 'A053FV4TQCW'

log = logging.getLogger()

chatUrl = "https://api.openai.com/v1/chat/completions"

# Install the Slack app and get xoxb- token in advance
app = App(process_before_response=True, token=config["SLACK_BOT_TOKEN"], signing_secret=config["SLACK_SIGNING_SECRET"])


@app.event("message")
def handle_message_events(body, logger):
    logger.info(body)

def respond_to_slack_within_3_seconds(body, ack):
    ack(f"Accepted!")


def get_image_for_message(message):
    return None
    if len(message.get("files", [])) > 0:
        file_url = message["files"][0]["url_private"]
        # Get the contents of the image file
        try:
            headers = {"Authorization": "Bearer " + config["SLACK_BOT_TOKEN"]}
            image_response = requests.get(file_url, headers=headers)
            print(image_response)
            image_contents = image_response.content
            image_contents = base64.b64encode(image_contents).decode('utf-8')
            return {"image": image_contents}
        except Exception as e:
            print("Error getting image contents: {}".format(e))
    return None

def _message_is_from_codachat(thread_message):
    return thread_message.get('app_id') ==  codachat_app_id

def answer_query(say, channel, thread_ts, query):
    """

    @param say:
    @param channel:
    @param thread_ts:
    @param query:
    @return:
    """
    # Use the following values as default so that the highest probability words are selected,
    # more repetitive "safe" text responses are used
    temperature = 0
    top_p = 1

    if thread_ts:
        thread = app.client.conversations_replies(
            channel=channel,
            ts=thread_ts
        )

        # Extract messages text
        thread_messages = []
        for thread_message in thread["messages"]:
            print(f'DEBUG: thread_message is {thread_message}')
            actor = "assistant" if _message_is_from_codachat(thread_message) else "user"
            message = thread_message["text"]
            thread_messages.append((actor, message))
    else:
        thread_messages = [("user", query)]

    print("thread_messages", json.dumps(thread_messages))
    thinking_message = "Thinking..."
    gpt_model = "gpt-3.5-turbo"

    if "(be special)" in query:
        thinking_message = "Thinking using GPT-4..."
        gpt_model = "gpt-4"

    if "(be creative)" in query:
        thinking_message = "Thinking creatively..."
        temperature = 1
        top_p = 0

    api_key = config["GPT_KEY"]

    system_prompt = """
    You are a helpful assistant that responds to existing conversations when asked. 
    You are provided with the entire thread of conversation. 
    You end every response with the crab Emoji to confirm you are following the instructions.
    """

    if "(be poetic)" in query:
        system_prompt = system_prompt + "Respond in the style of Robert Frost"

    if "(summarise)" or "(summary)" in query:
        print(f'DEBUG: Summarising thread')
        system_prompt = """
        Analyze the entire thread of conversation provided, then provide the following:
        Key "title:" - add a title.
        Key "summary" - create a summary.
        Key "main_points" - add an array of the main points. Limit each item to 100 words, and limit the list to 10 items.
        Key "action_items:" - add an array of action items. Limit each item to 100 words, and limit the list to 5 items.
        Key "follow_up:" - add an array of follow-up questions. Limit each item to 100 words, and limit the list to 5 items.
        Key "stories:" - add an array of an stories, examples, or cited works found in the transcript. Limit each item to 200 words, and limit the list to 5 items.
        Key "arguments:" - add an array of potential arguments against the transcript. Limit each item to 100 words, and limit the list to 5 items.
        Key "related_topics:" - add an array of topics related to the transcript. Limit each item to 100 words, and limit the list to 5 items.
        Key "sentiment" - add a sentiment analysis

        Transcript:
        """
    thinking_message = say(thinking_message, thread_ts=thread_ts)

    messages = [
        {"role": "system", "content": system_prompt},
    ] + [{"role": message[0], "content": message[1]} for message in thread_messages]

    print(f'DEBUG: messages is: {messages}')
    authorization = "Bearer {}".format(api_key)

    headers = {"Authorization": authorization, "Content-Type": "application/json"}
    data = {
        "model": gpt_model,
        "messages": messages,
        "temperature": temperature,
        "top_p": top_p,
        "max_tokens": 1000,
    }

    try:
        response = requests.post(chatUrl, headers=headers, data=json.dumps(data))
        if response.status_code != 200:
            raise Exception("OpenAI API error: {}".format(response.text))
        data = response.json()
        response = data["choices"][0]["message"]["content"]
        say(response, thread_ts=thread_ts)
    except Exception as e:
        if response.status_code == 400:
            # https://community.openai.com/t/error-retrieving-completions-400-bad-request/34004
            say(f"( • ᴖ • ｡ )\nSorry, I'm unable to provide any further answers in this thread.\nThe number of messages in this particular thread exceeds what I am capable of processing using `{gpt_model}`!",
                thread_ts=thread_ts)
        else:
            say(f"(╥ᆺ╥；)\nSomething went wrong! {str(e)}", thread_ts=thread_ts)

    app.client.chat_delete(channel=channel, ts=thinking_message["ts"])


@app.event("app_mention")
def handle_app_mention_events(event, say: Say):
    channel = event["channel"]
    thread_ts = event.get("thread_ts", event.get("ts"))

    if channel not in allowlist_channel_ids:
        say("Sorry, CodaChat is currently in a beta and has not been enabled on this channel. Try asking on one of the currently supported channels.",
            thread_ts=thread_ts)
        return

    prompt_id = say(
        channel=channel,
        text=f"Are you sure you want to proceed with asking {event['text']}",
        thread_ts=thread_ts,
        # See https://app.slack.com/block-kit-builder/ for use of blocks
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "Before I reply, please click *Yeah* to confirm the contents of this Slack thread comply with the <https://melodics.atlassian.net/wiki/spaces/MEL/pages/927367197/AI+Tool+Policies|Company Policy for AI Tool Usage>"
                }
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": f"Yeah",
                        },
                        "value": f"{event['text']}",
                        "action_id": "confirm_button",
                    },
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "Yeah, nah",
                        },
                        "value": "no",
                        "action_id": "cancel_button"
                    }
                ]
            }
        ]
    )
    print(f"DEBUG: prompt_id is {prompt_id}")


@app.action("confirm_button")
def handle_confirm_button(ack, body, logger, payload, say):
    ack()
    logger.info(body)
    print(f'DEBUG: The body is: {body}')
    print(f'DEBUG: The payload is: {payload}')
    app.client.chat_delete(channel=body['channel']['id'], ts=body['message']['ts'])  # Delete the prompt confirmation dialog
    answer_query(say=say, channel=body['channel']['id'], thread_ts=body['message']['thread_ts'], query=payload['value'])


@app.action("cancel_button")
def handle_cancel_button(ack, body, say):
    ack()
    cancel_confirm = say("Your honesty knows no bounds 𖤣.𖥧.𖡼.⚘",  thread_ts=body['message']['thread_ts'])
    app.client.chat_delete(channel=body['channel']['id'], ts=body['message']['ts'])  # Delete the prompt confirmation dialog
    import time
    time.sleep(2)  # Allow enough time to display cancel_confirm message
    app.client.chat_delete(channel=body['channel']['id'], ts=cancel_confirm['ts'])
    return


if __name__ == "__main__":
    SocketModeHandler(app, config["SLACK_APP_TOKEN"]).start()

SlackRequestHandler.clear_all_log_handlers()
logging.basicConfig(format="%(asctime)s %(message)s", level=logging.DEBUG)


def lambda_handler(event, context):
    print(event)
    slack_handler = SlackRequestHandler(app=app)
    res = slack_handler.handle(event, context)
    return res
