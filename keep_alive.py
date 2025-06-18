from flask import Flask
from threading import Thread
import os

app = Flask("")

@app.route("/")
def home():
    return "I am alive!"

def run():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

def keep_alive():
    t = Thread(target=run)
    t.daemon = True
    t.start()
