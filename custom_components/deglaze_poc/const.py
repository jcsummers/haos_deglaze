"""Constants for the unofficial Deglaze Home Assistant integration."""
from datetime import timedelta

DOMAIN = "deglaze_poc"  # Keep the domain stable so the working POC entry remains usable.
PLATFORMS = ["sensor"]
UPDATE_INTERVAL = timedelta(minutes=5)
RECIPE_SYNC_INTERVAL = timedelta(minutes=60)
MEAL_PLAN_SYNC_INTERVAL = timedelta(minutes=15)
MEAL_PLAN_DAYS_AHEAD = 30

DEGLAZE_BASE_URL = "https://gateway.deglaze.app/v1"
FIREBASE_SIGN_IN_URL = "https://identitytoolkit.googleapis.com/v1/accounts:signInWithEmailLink"
FIREBASE_REFRESH_URL = "https://securetoken.googleapis.com/v1/token"
ALLOWED_ACTION_HOST = "deglaze-prod.firebaseapp.com"
ALLOWED_ACTION_PATH = "/__/auth/action"
ALLOWED_CONTINUE_HOST = "web.deglaze.app"

CONF_EMAIL = "email"
CONF_FIREBASE_API_KEY = "firebase_api_key"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_USER_ID = "user_id"
CONF_DEVICE_ID = "device_id"

# Observed in Deglaze browser traffic; may change with a frontend deployment.
DEGLAZE_WEB_BUILD_HASH = "5696f47"
