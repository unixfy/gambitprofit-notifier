############## HOW TO USE ##############
# Run on AWS Lambda using main() function as handler. Set environment variables (ENCRYPTED) to hold credentials.

# TODO: This script as-is is not functional!!! Many changes need to be made - namely, removing the dependency on Amazon S3 for data storage.
import json
import requests
import dateutil.parser
import boto3
from datetime import datetime, timezone
from termcolor import colored
from colorama import init

# Init colorama, this is so colors will work correctly on Windows machines
init()

###################### START user configuration section ######################
# API endpoint (needs to include full path)
API_ENDPOINT = "https://api.gambitprofit.com/gambit-plays"
API_PARAMS = {
    "_limit": 200,
    "_sort": "PlayDate:DESC"
}

# Set LOCAL storage file location (note that this would be stored in an S3 bucket on Lambda)
# Needs to be an ABSOLUTE PATH
storage_file = "/tmp/storage.txt"

# Set REMOTE (S3) storage file location
storage_file_s3 = "storage.txt"

# Percentage profit NoRisk at which a notification will be triggered.
notif_threshold = 2.63

# Array of Discord webhook URLs
# Unixfy server, BM server, SB server
discord_webhooks = [
"***REMOVED***",
"***REMOVED***",
"***REMOVED***"
]

# Headers to send to Discord webhook
discord_headers = {
    "Content-Type": "application/json"
}

# ElasticEmail configuration
# ElasticEmail API key
elasticemail_apikey = "***REMOVED***"

###################### END user configuration section ######################

print("Fetched API data.")

# Init Boto3 S3 client
s3 = boto3.client("s3")

# This function will search storage text file by id, returning true if id is not in the file; false if it is
def getData(id):
    try:
        storage = open(storage_file, "r+")
        if id not in storage.read():
            return True
        else:
            return False
        storage.close()
    except:
        return True


# This function puts the play into the storage file, in format: {id} Team1 (1.23) v. Team2 (2.34) {current time}.
def putData(gamename, id):
    storage = open(storage_file, "a+")
    storage.write(id + " " + gamename + " " + str(datetime.now(timezone.utc)) + "\n")
    storage.close()


# This function queues items for notifs
def addToQueue(gamename, id, profitpercard):
    # Add item to queue (which is stored as json object)
    queue.append(
        {
            "gamename": gamename,
            "id": id,
            "profitpercard": profitpercard
        }
    )

# This function sends one condensed notification based on the queue
def sendNotifs():
    # Discord notifications
    discord_payload = {
        "content": "",
        "embeds": [
            {
                "title": ":money_mouth: New Good Gambit Plays Found",
                "url": "https://gambitprofit.com",
                "description": "Visit [:link: GambitProfit.com](https://gambitprofit.com) for more information.\n\n**Are you annoyed by these notifications**? Instead of leaving :poop: reactions, please consider giving some feedback: https://forms.gle/o4Nb3YvU4tndtepG7",
                "color": 1205222,
                "fields": [

                ],
                "author": {
                    "name": "GambitProfit Notifier",
                    "url": "https://gambitprofit.com"
                },
                "footer": {
                    "text": "You can view more information about these bets, including how much to bet, at GambitProfit.com. \nNote: percent profit is calculated using 1000 tokens."
                }
            }
        ],
        "username": "Gambit Plays",
        "avatar_url": "https://share.unixfy.net/direct/4of9mxq3.png"
    }

    # Add items from queue to the payload
    for item in queue:
        discord_payload["embeds"][0]["fields"].append(
            {
                "name": ":arrow_right: " + item["gamename"],
                "value": str(item["profitpercard"]) + "% profit or more"
            }
        )

    # Send notification to each Discord webhook
    for item in discord_webhooks:
        # Add ping if the webhook is the SB server one
        if "***REMOVED***" in item:
            discord_payload["content"] = "Gambit Plays were found! - <@&754060824850464879>"
        else:
            discord_payload["content"] = "Gambit Plays were found!"

        print(colored("Sending POST to Discord webhook now!", "blue"))
        discord_post = requests.post(item, data=json.dumps(discord_payload), headers=discord_headers)
        print(discord_post.status_code)


    # ElasticEmail email notifications
    # This variable will hold all the content of the "plays" template token
    email_text = ""

    # Parameters for ElasticEmail API
    elasticemail_parameters = {
        "apikey": elasticemail_apikey,
        "lists": "GambitProfit Notifications",
        "template": "GambitProfitBetNotificationMail",
        "channel": "HTTP API",
        "charset": "utf-8"
    }

    # Construct the "plays" template token content (bullet point for each play)
    for item in queue:
        email_text = email_text + "<li>" + item["gamename"] + " - " + str(item["profitpercard"]) + "% profit or more"

    # Add constructed content to the API request params
    elasticemail_parameters["merge_plays"] = "<ul>" + email_text + "</ul>"

    # Fire off API request
    print(colored("Sending POST to ElasticEmail API now!", "blue"))
    elasticemail_post = requests.post("https://api.elasticemail.com/v2/email/send", params=elasticemail_parameters)
    print(elasticemail_post.status_code, elasticemail_post.text)


# This is the lambda handler function
def main(event, context):
    global queue
    queue = []

    api_get = requests.get(url=API_ENDPOINT, params=API_PARAMS)
    api_data = api_get.json()
    # Try to download storage file from S3
    try:
        s3.download_file("gambitprofit-notifier-storage", storage_file_s3, storage_file)
        print(colored("Downloaded storage file from S3.", "blue"))
    except:
        print(colored("Failed to download storage file from S3.", "blue"))
        pass
    # Loop through the data returned by the API
    for bet in api_data:
        # Time until play starts calculator
        date_utc = datetime.now(timezone.utc)
        date_start = dateutil.parser.isoparse(bet["PlayDate"])
        difference = date_start - date_utc

        # Construct full game name in format: Team1 (1.23) v. Team2 (2.34)
        gamename = bet["Team1"]["Name"] + " (" + str(bet["Team1"]["Reward"]) + ") v. " + bet["Team2"][
            "Name"] + " (" + str(bet["Team2"]["Reward"]) + ")"

        # Make sure there are at least 30 min until play starts, and the norisk profitpercard is at least 4%
        if (difference.total_seconds() / 60) > 30 and bet["Calc"]["NoRisk"]["ProfitPerCard"] >= notif_threshold:
            # Prelim passed means the game hasn't started, and is profitable enough
            print(colored(gamename + " => PRELIM PASSED", "yellow"))
            # Validate if the game is in the storage file (i.e. already notified). If it is not, then notify; otherwise, pass
            if getData(bet["_id"]):
                # Passed OK means the game prelim passed AND wasn't already notified in the past
                print(colored(gamename + " => PASSED OK", "green"))
                # Add to notification queue
                addToQueue(gamename, bet["_id"], bet["Calc"]["NoRisk"]["ProfitPerCard"])
                # Store play into storage file, to prevent dupes
                putData(gamename, bet["_id"])
            else:
                # Already sent means the game prelim passed but was already notified
                print(colored(gamename + " => ALREADY SENT", "yellow"))
                pass
        else:
            # Fail means the game didn't pass the criteria ;(
            print(colored(gamename + " => FAIL", "red"))

    # Now that all the bets have been processed, send notifications IF queue is not empty
    if len(queue) > 0:
        print(colored("Sending notifications now.", "blue"))
        sendNotifs()
    else:
        print(colored("Script succeeded, but no notifications need to be sent.", "blue"))

    # Write storage file to S3
    s3.upload_file(storage_file, "gambitprofit-notifier-storage", storage_file_s3)
    print(colored("Wrote storage file back to S3.", "blue"))