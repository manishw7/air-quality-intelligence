import os
import pandas as pd
import numpy as np
import pickle
import joblib
import tensorflow as tf
from flask import Flask, request, jsonify, session, send_from_directory,render_template
from flask_cors import CORS
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import requests
from datetime import datetime, timedelta, timezone
from database import get_db_connection
import time
import json
from io import StringIO

pd.set_option('future.no_silent_downcasting', True)

# --- Initialize Flask App ---
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'a_super_secret_key_for_dev')
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)
CORS(app)

@app.route('/')
def index():
    """Renders the welcome page."""
    return render_template('index.html')

@app.route('/login')
def login_page():
    """Renders the login page."""
    return render_template('login.html')

@app.route('/register')
def register_page():
    """Renders the registration page."""
    return render_template('register.html')

@app.route('/dashboard')
def dashboard_page():
    """Renders the main dashboard."""
    return render_template('dashboard.html')

@app.route('/profile')
@login_required
def profile_page():
    """Renders the user profile page."""
    return render_template('profile.html')

# --- Configuration & File Paths ---
LATITUDE = 27.7172
LONGITUDE = 85.3240
N_PAST = 72
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(BASE_DIR, 'data', 'cache')
CACHE_FILE = os.path.join(CACHE_DIR, 'live_df_cache.json')
CACHE_TIMEOUT = 3600
os.makedirs(CACHE_DIR, exist_ok=True)

# --- Model & Static Data Paths ---
REGRESSION_MODEL_PATH = os.path.join(BASE_DIR, 'models', 'model.pkl')
PERSONAL_RISK_MODEL_PATH = os.path.join(BASE_DIR, 'models', 'personal_risk_model.pkl')
LSTM_MODEL_PATH = os.path.join(BASE_DIR, 'models', 'lstm_model.keras')
SCALER_PATH = os.path.join(BASE_DIR, 'models', 'scaler.pkl')
SOIL_IMPUTER_PATH = os.path.join(BASE_DIR, 'models', 'soil_imputer.pkl')
DATA_PATH = os.path.join(BASE_DIR, 'data', 'processed', 'processed_data.csv')

# --- Load Models & Static Data ---
regression_model, personal_risk_model, soil_imputer_model, lstm_model, scaler = None, None, None, None, None
REGRESSION_FEATURE_NAMES, SCALER_FEATURE_NAMES = [], []
df_static = pd.DataFrame()
try:
    with open(REGRESSION_MODEL_PATH, "rb") as f: regression_model = pickle.load(f)
    print("Main AQI regression model loaded successfully.")
except Exception as e: print(f"CRITICAL ERROR: Could not load main AQI regression model: {e}")
try:
    with open(PERSONAL_RISK_MODEL_PATH, "rb") as f: personal_risk_model = pickle.load(f)
    print("Personal risk model loaded successfully.")
except Exception as e: print(f"CRITICAL WARNING: Could not load personal risk model: {e}")
try:
    soil_imputer_model = joblib.load(SOIL_IMPUTER_PATH)
    print("Soil imputation model loaded successfully.")
except Exception as e: print(f"CRITICAL WARNING: Could not load soil imputer model: {e}")
try:
    lstm_model = tf.keras.models.load_model(LSTM_MODEL_PATH)
    scaler = joblib.load(SCALER_PATH)
    SCALER_FEATURE_NAMES = scaler.get_feature_names_out()
    print("LSTM Model and Scaler loaded successfully.")
    if scaler:
        REGRESSION_FEATURE_NAMES = [name for name in SCALER_FEATURE_NAMES if 'aqi' not in name.lower()]
        print("Successfully derived regression feature names from the scaler.")
except Exception as e: print(f"CRITICAL ERROR: Could not load LSTM model or scaler: {e}")
try:
    df_static = pd.read_csv(DATA_PATH, parse_dates=['Datetime'], index_col='Datetime')
    df_static = df_static.asfreq('h')
    if df_static.index.tz is None: df_static.index = df_static.index.tz_localize('UTC')
    print(f"Successfully loaded and localized static data for EDA from {DATA_PATH}")
except Exception as e: print(f"WARNING: Could not load static data for EDA dashboard: {e}")


# --- Caching Logic ---
def get_cached_or_create_live_dataframe():
    now = time.time()
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, 'r') as f:
            try:
                cache_data = json.load(f)
                if now - cache_data.get('timestamp', 0) < CACHE_TIMEOUT:
                    print("Returning cached dataframe from file.")
                    df = pd.read_json(StringIO(cache_data['data']), orient='split')
                    df.index = pd.to_datetime(df.index, unit='ms', utc=True)
                    return df
            except (json.JSONDecodeError, KeyError) as e: print(f"Cache file corrupted, fetching new data. Error: {e}")
    print("Cache expired or not found. Fetching new live dataframe.")
    df = create_live_dataframe(end_date=datetime.now(timezone.utc))
    df_json_str = df.to_json(orient='split')
    cache_content = {'timestamp': now, 'data': df_json_str}
    with open(CACHE_FILE, 'w') as f: json.dump(cache_content, f)
    return df

# --- User Model & Auth Logic ---
class User(UserMixin):
    def __init__(self, id, username, password_hash, age=None, conditions=None):
        self.id, self.username, self.password, self.age, self.conditions = id, username, password_hash, age, conditions
login_manager = LoginManager()
login_manager.init_app(app)
@login_manager.user_loader
def load_user(user_id):
    conn = get_db_connection()
    if not conn: return None
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    user_data = cursor.fetchone()
    cursor.close(); conn.close()
    if user_data: return User(user_data['id'], user_data['username'], user_data['password'], user_data['age'], user_data['conditions'])
    return None

# --- Helper Functions ---
def prepare_personal_model_input(ambient_aqi, user):
    age = user.age if user.age else 30
    conditions = user.conditions.lower() if user.conditions else ""
    has_respiratory = 1 if any(c in conditions for c in ['asthma', 'copd', 'respiratory']) else 0
    has_heart = 1 if any(c in conditions for c in ['heart', 'cardiovascular']) else 0
    return pd.DataFrame({'ambient_aqi': [ambient_aqi], 'age': [age], 'has_respiratory_condition': [has_respiratory], 'has_heart_condition': [has_heart]})
def get_personal_advice(aqi, user):
    if not user or not user.is_authenticated or not (user.age or user.conditions): return None
    advice_parts = []
    category, _, _, _ = categorize_aqi(aqi)
    sensitive = ["Unhealthy for Sensitive Groups", "Unhealthy", "Very Unhealthy", "Hazardous"]
    if user.age and user.age > 60 and category in sensitive: advice_parts.append("Given your age, it is strongly recommended to stay indoors.")
    if user.conditions:
        conditions = user.conditions.lower()
        if any(c in conditions for c in ['asthma', 'copd', 'respiratory']) and category in sensitive: advice_parts.append("Your respiratory condition puts you at high risk. Avoid all outdoor activity.")
        if any(c in conditions for c in ['heart', 'cardiovascular']) and category in sensitive: advice_parts.append("Your heart condition makes you more vulnerable. Avoid strenuous activity.")
    return " ".join(advice_parts) if advice_parts else "The current air quality should not pose a significant additional risk based on your profile."
def categorize_aqi(aqi):
    if aqi is None or np.isnan(aqi): return "Unknown", "#808080", "Data not available.", "❓"
    aqi = int(aqi)
    if aqi <= 50: return "Good", "#28a745", "Air quality is satisfactory.", "😊"
    elif aqi <= 100: return "Moderate", "#ffc107", "Some pollutants may be a moderate health concern.", "😐"
    elif aqi <= 150: return "Unhealthy for Sensitive Groups", "#fd7e14", "Members of sensitive groups may experience health effects.", "😷"
    elif aqi <= 200: return "Unhealthy", "#dc3545", "Everyone may begin to experience health effects.", "🤢"
    elif aqi <= 300: return "Very Unhealthy", "#8f3e97", "Health warnings of emergency conditions.", "😵"
    else: return "Hazardous", "#7f0000", "Health alert: everyone should avoid all outdoor exertion.", "☠️"

# --- Live Dataframe Creation ---
def create_live_dataframe(end_date):
    if df_static.empty: raise ValueError("Static historical data is not loaded.")
    last_static_date = df_static.index.max()
    if end_date <= last_static_date: return df_static[df_static.index <= end_date]
    gap_start_date = last_static_date + timedelta(hours=1)
    weather_params="temperature_2m,relative_humidity_2m,precipitation,cloud_cover,surface_pressure,pressure_msl,wind_speed_10m,wind_direction_10m,wind_gusts_10m,uv_index"
    weather_url = f"https://archive-api.open-meteo.com/v1/archive?latitude={LATITUDE}&longitude={LONGITUDE}&start_date={gap_start_date.strftime('%Y-%m-%d')}&end_date={end_date.strftime('%Y-%m-%d')}&hourly={weather_params}&timezone=UTC"
    weather_response = requests.get(weather_url); weather_response.raise_for_status()
    weather_data = weather_response.json()['hourly']
    aq_params = "pm10,pm2_5,carbon_monoxide,nitrogen_dioxide,sulphur_dioxide,ozone"
    aq_url = f"https://air-quality-api.open-meteo.com/v1/air-quality?latitude={LATITUDE}&longitude={LONGITUDE}&start_date={gap_start_date.strftime('%Y-%m-%d')}&end_date={end_date.strftime('%Y-%m-%d')}&hourly={aq_params}&timezone=UTC"
    aq_response = requests.get(aq_url); aq_response.raise_for_status()
    aq_data = aq_response.json()['hourly']
    df_gap = pd.DataFrame(weather_data).merge(pd.DataFrame(aq_data), on='time').rename(columns={'time': 'Datetime'})
    df_gap['Datetime'] = pd.to_datetime(df_gap['Datetime'], utc=True)
    df_gap.set_index('Datetime', inplace=True)
    df_gap.ffill(inplace=True); df_gap.bfill(inplace=True); df_gap.fillna(0, inplace=True)
    api_to_model_map = {"pm10":"PM10 (μg/m³)","pm2_5":"PM2.5 (μg/m³)","carbon_monoxide":"CO (μg/m³)","nitrogen_dioxide":"NO2 (μg/m³)","sulphur_dioxide":"SO2 (μg/m³)","ozone":"O3 (μg/m³)","uv_index":"UV_Index","temperature_2m":"Temp (°C)","relative_humidity_2m":"Humidity (%)","wind_direction_10m":"Wind_Direction (°)","precipitation":"Precipitation (mm)","surface_pressure":"Surface_Pressure (hPa)","pressure_msl":"Pressure_MSL (hPa)","wind_speed_10m":"Wind_Speed (km/h)","wind_gusts_10m":"Wind_Gusts (km/h)","cloud_cover":"Cloud_Cover (%)"}
    df_gap.rename(columns=api_to_model_map, inplace=True)
    df_gap['hour'] = df_gap.index.hour; df_gap['month'] = df_gap.index.month
    imputer_features = ['Temp (°C)', 'UV_Index', 'Cloud_Cover (%)', 'hour', 'month']
    predicted_soil = soil_imputer_model.predict(df_gap[imputer_features])
    df_gap['Soil_Temp (°C)'] = predicted_soil[:, 0]; df_gap['Soil_Moisture (m³/m³)'] = predicted_soil[:, 1]
    df_for_rf = df_gap[REGRESSION_FEATURE_NAMES]
    predicted_aqi = regression_model.predict(df_for_rf)
    df_gap['AQI'] = np.clip(predicted_aqi, 0, None)
    df_live = pd.concat([df_static, df_gap[df_static.columns]])
    df_live = df_live[~df_live.index.duplicated(keep='last')]
    return df_live

@app.before_request
def make_session_permanent(): session.permanent = True

@app.route('/api/session_status')
def session_status():
    if current_user.is_authenticated:
        return jsonify({"logged_in": True, "user": {"username": current_user.username, "age": current_user.age, "conditions": current_user.conditions}, "features": REGRESSION_FEATURE_NAMES})
    return jsonify({"logged_in": False, "features": REGRESSION_FEATURE_NAMES})

@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json(); username, password = data['username'], data['password']
    conn = get_db_connection(); cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
    user_data = cursor.fetchone(); cursor.close(); conn.close()
    if user_data and check_password_hash(user_data['password'], password):
        user_obj = User(user_data['id'], user_data['username'], user_data['password'], user_data['age'], user_data['conditions'])
        login_user(user_obj, remember=True)
        return jsonify({"success": True, "message": "Login successful!", "user": {"username": user_data['username'], "age": user_data['age'], "conditions": user_data['conditions']}})
    return jsonify({"success": False, "message": "Invalid username or password."}), 401
@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json(); username, password = data['username'], data['password']
    conn = get_db_connection(); cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
    if cursor.fetchone():
        cursor.close(); conn.close()
        return jsonify({"success": False, "message": "Username already exists."}), 409
    cursor.execute("INSERT INTO users (username, password) VALUES (%s, %s)", (username, generate_password_hash(password)))
    conn.commit(); cursor.close(); conn.close()
    return jsonify({"success": True, "message": "Registration successful! Please log in."})
@app.route('/api/logout', methods=['POST'])
@login_required
def logout():
    logout_user()
    return jsonify({"success": True})
@app.route('/api/profile', methods=['POST'])
@login_required
def profile():
    data = request.get_json(); age = data.get('age') or None; conditions = data.get('conditions', '').strip() or None
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute("UPDATE users SET age = %s, conditions = %s WHERE id = %s", (age, conditions, current_user.id))
    conn.commit(); cursor.close(); conn.close()
    current_user.age = int(age) if age else None; current_user.conditions = conditions
    return jsonify({"success": True, "message": "Profile updated successfully!", "user": {"age": age, "conditions": conditions}})

@app.route('/api/predict', methods=['POST'])
def predict():
    try:
        data = request.get_json()
        input_df = pd.DataFrame([data], columns=REGRESSION_FEATURE_NAMES)
        ambient_aqi = max(0, regression_model.predict(input_df)[0])
        cat, color, advice, emoji = categorize_aqi(ambient_aqi)
        perceived_aqi, personal_advice = None, None
        
        # <<< DEFINITIVE FIX: Check for authentication AND profile data >>>
        if current_user.is_authenticated and (current_user.age or current_user.conditions):
            personal_input_df = prepare_personal_model_input(ambient_aqi, current_user)
            perceived_aqi_pred = personal_risk_model.predict(personal_input_df)[0]
            perceived_aqi = max(ambient_aqi, perceived_aqi_pred)
            personal_advice = get_personal_advice(perceived_aqi, current_user)
            
        return jsonify({'predicted_aqi': round(ambient_aqi, 2), 'perceived_aqi': round(perceived_aqi, 2) if perceived_aqi is not None else None, 'category': cat, 'color': color, 'advice': advice, 'emoji': emoji, 'personal_advice': personal_advice})
    except Exception as e: return jsonify({"error": f"An error occurred: {e}"}), 400

@app.route('/api/forecast_lstm', methods=['POST'])
def forecast_lstm_live():
    try:
        hours = int(request.get_json().get('hours', 24))
        df_live_hist = get_cached_or_create_live_dataframe()
        df_for_lstm = df_live_hist[SCALER_FEATURE_NAMES].tail(N_PAST)
        if len(df_for_lstm) < N_PAST: return jsonify({"error": "Not enough historical data."}), 500
        scaled_sequence = scaler.transform(df_for_lstm)
        input_data = scaled_sequence.reshape(1, N_PAST, len(SCALER_FEATURE_NAMES))
        scaled_prediction = lstm_model.predict(input_data)[0]
        dummy_array = np.zeros((len(scaled_prediction), len(SCALER_FEATURE_NAMES))); dummy_array[:, 0] = scaled_prediction.flatten()
        final_aqi_prediction = np.clip(scaler.inverse_transform(dummy_array)[:, 0], 0, None)
        last_ts = df_for_lstm.index[-1]
        future_ts = [last_ts + pd.Timedelta(hours=i) for i in range(1, len(final_aqi_prediction) + 1)]
        forecast_data = []
        for ts, ambient_val in zip(future_ts, final_aqi_prediction):
            perceived_val = None
            # <<< DEFINITIVE FIX: Check for authentication AND profile data >>>
            if current_user.is_authenticated and (current_user.age or current_user.conditions):
                personal_input_df = prepare_personal_model_input(ambient_val, current_user)
                perceived_pred = personal_risk_model.predict(personal_input_df)[0]
                perceived_val = max(ambient_val, perceived_pred)
            forecast_data.append({'ds': ts.strftime('%Y-%m-%dT%H:%M:%S'), 'yhat': round(float(ambient_val), 2), 'perceived_yhat': round(float(perceived_val), 2) if perceived_val is not None else None})
        historical_data_for_chart = [{'ds': idx.strftime('%Y-%m-%dT%H:%M:%S'), 'yhat': round(row['AQI'], 2)} for idx, row in df_for_lstm.iterrows()]
        return jsonify({"historical": historical_data_for_chart, "forecast": forecast_data[:hours]})
    except Exception as e: return jsonify({"error": f"An error occurred during forecasting: {e}"}), 500

@app.route('/api/historical_data')
def get_historical_data_live():
    try:
        df_live = get_cached_or_create_live_dataframe()
        now = datetime.now(timezone.utc)
        df_chart_data = df_live[df_live.index >= now - timedelta(days=7)]
        return jsonify([{'ds': idx.strftime('%Y-%m-%dT%H:%M:%S'), 'yhat': round(row['AQI'], 2)} for idx, row in df_chart_data.iterrows()])
    except Exception as e: return jsonify([]), 500
@app.route('/api/fetch_current_data')
def fetch_current_data():
    try:
        df_live = get_cached_or_create_live_dataframe()
        latest_data = df_live.iloc[-1].to_dict()
        for key, value in latest_data.items():
            if isinstance(value, np.generic): latest_data[key] = value.item()
        return jsonify({"source": "Live API (Bridged)", "data": latest_data})
    except Exception as e: return jsonify({"error": f"An error occurred: {e}"}), 500
@app.route('/api/eda_data')
def get_eda_data():
    if df_static.empty: return jsonify({"error": "Static data for analysis is not loaded."}), 500
    try:
        start_str, end_str = request.args.get('start'), request.args.get('end')
        end = pd.to_datetime(end_str, utc=True) if end_str else df_static.index.max()
        start = pd.to_datetime(start_str, utc=True) if start_str else end - pd.DateOffset(years=1)
        df_filtered = df_static.loc[start:end].copy()
        if df_filtered.empty: return jsonify({"error": "No data available for the selected date range."}), 404
        daily_avg = df_filtered['AQI'].resample('D').mean()
        hist, bins = np.histogram(df_filtered['AQI'].dropna(), bins=20)
        cat_counts = df_filtered['AQI'].apply(lambda x: categorize_aqi(x)[0]).value_counts()
        stats = df_filtered['AQI'].agg(['mean', 'median', 'max', 'min']).round(2)
        df_table = df_filtered[['AQI', 'Temp (°C)', 'Humidity (%)', 'Wind_Speed (km/h)']].round(1).tail(500)
        df_table.index.name = 'Datetime'
        df_table.reset_index(inplace=True)
        table_data = {"columns": df_table.columns.tolist(), "data": df_table.to_dict(orient='records')}
        by_month = df_filtered.groupby(df_filtered.index.month_name())['AQI'].mean().reindex(['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']).dropna()
        by_day = df_filtered.groupby(df_filtered.index.day_name())['AQI'].mean().reindex(['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']).dropna()
        by_hour = df_filtered.groupby(df_filtered.index.hour)['AQI'].mean()
        return jsonify({
            "table_data": table_data,
            "time_series": {
                "aqi_over_time": {"labels": daily_avg.index.strftime('%Y-%m-%d').tolist(), "values": daily_avg.dropna().round(2).tolist()},
                "dist": {"labels": [f"{int(b)}-{int(bins[i+1])}" for i, b in enumerate(bins[:-1])], "values": hist.tolist()},
                "categories": {"labels": cat_counts.index.tolist(), "values": cat_counts.values.tolist()},
                "stats": stats.to_dict()
            },
            "deep_dive": {
                "by_month": {"labels": by_month.index.tolist(), "values": by_month.round(2).tolist()},
                "by_day_of_week": {"labels": by_day.index.tolist(), "values": by_day.round(2).tolist()},
                "by_hour": {"labels": by_hour.index.map(lambda h: f"{h:02d}:00").tolist(), "values": by_hour.round(2).tolist()}
            }
        })
    except Exception as e:
        print(f"Error in get_eda_data: {e}")
        return jsonify({"error": f"An error occurred during data analysis: {str(e)}"}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5001)

