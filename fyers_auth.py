from fyers_apiv3 import fyersModel
import os

APP_ID = os.environ.get("FYERS_APP_ID")
SECRET_KEY = os.environ.get("FYERS_SECRET_KEY")
REDIRECT_URI = "https://127.0.0.1"

session = fyersModel.SessionModel(
    client_id=APP_ID,
    secret_key=SECRET_KEY,
    redirect_uri=REDIRECT_URI,
    response_type="code",
    grant_type="authorization_code"
)

auth_url = session.generate_authcode()
print("AUTH URL:", auth_url)
