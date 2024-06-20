from flask import Flask, request, jsonify
import requests
import logging
import string
import random
import time
from tenacity import retry, wait_fixed, stop_after_attempt

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO)

# Global payload to store the original payload
global_payload = {}

# Helper function to generate a unique reference number
def generate_resnum():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=12))

# Function to send request and get token
def get_token(url, payload):
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        if data.get("status") == 1:
            token = data.get("token")
            logging.info(f"Received token: {token}")
            global_payload = payload
            return {'token': token}
        else:
            error_desc = data.get("errorDesc")
            logging.error(f"Error: {error_desc}")
            return {'error': error_desc}
    except requests.exceptions.RequestException as error:
        logging.error(f"Request error: {error}")
        return {'error': str(error)}

# Route to handle token generation
@app.route('/get-token', methods=['POST', 'GET'])
def handle_get_token():
    data = request.get_json() if request.is_json else request.form.to_dict()
    url = 'https://sep.shaparak.ir/onlinepg/onlinepg'
    resnum = generate_resnum()

    payload = {
        "action": "token",
        "TerminalId": "your_terminal_id",
        "Amount": data.get("Amount"),
        "ResNum": resnum,
        "RedirectUrl": "http://mysite.com/receipt",
        "CellNumber": "9120000000",
    }

    result = get_token(url, payload)
    return jsonify(result), 200 if 'token' in result else 500 # return token to frontend for redirect

# Route to handle payment status
@app.route('/receipt', methods=['POST'])
def payment_status():
    payment_data = request.get_json() if request.is_json else request.form.to_dict()
    status = payment_data.get('Status')

    if status == '2':
        payment_exists(payment_data)
    else:
        status_messages = {
            '1': 'کاربر انصراف داده است.',
            '2': 'پرداخت با موفقیت انجام شد.',
            '3': 'پرداخت انجام نشد.',
            '4': 'کاربر در بازه زمانی تعیین شده پاسخی ارسال نکرده است.',
            '5': 'پارامتر های ارسالی نامعتبر است.',
            '8': 'آدرس سرور پذیرنده نامعتبر است.',
            '10': 'توکن ارسال شده یافت نشد.',
            '11': 'با این شماره ترمینال فقط تراکنش های توکنی قابل پرداخت هستند.',
            '12': 'شماره ترمینال ارسال شده یافت نشد.',
        }
        message = status_messages.get(status, 'خطای نامشخص')
        logging.error(f"Error: {message}")
        return jsonify({'error': message}), 500

# Function to check if payment exists
def payment_exists(payment_data):
    logging.info("RefNum checking on database ...")
    ref_num = payment_data.get('RefNum')
    # Example DB check: replace with your logic
    if ref_num:
        verify_transaction(payment_data, global_payload.get('Amount'))
    else:
        logging.error("تراکنش تکراری است.")

# Retry configuration
@retry(wait=wait_fixed(5), stop=stop_after_attempt(3))
def verify_transaction(payment_data, amount):
    url = 'https://sep.shaparak.ir/verifyTxnRandomSessionkey/ipg/VerifyTransaction'
    data = {
        "RefNum": payment_data.get("RefNum"),
        "TerminalNumber": payment_data.get("TerminalNumber")
    }
    response = requests.post(url, json=data)
    response.raise_for_status()

    response_json = response.json()
    result_code = response_json.get("ResultCode")

    if result_code == 0:
        transaction_detail = response_json.get('TransactionDetail', {})
        original_amount = int(transaction_detail.get('OrginalAmount'))
        affective_amount = int(transaction_detail.get('AffectiveAmount'))
        if original_amount == amount and affective_amount == amount:
            save_payment_to_db(payment_data)
            logging.info("Transaction verified successfully and saved to db")
        else:
            reverse_transaction(payment_data)
    else:
        handle_transaction_error(result_code)

def handle_transaction_error(result_code):
    result_messages = {
        '-2': 'تراکنش یافت نشد.',
        '-6': 'بیش از نیم ساعت از زمان اجرای تراکنش گذشته است.',
        '2': 'درخواست تکراری می باشد.',
        '-105': 'ترمینال ارسالی در سیستم موجود نمی‌باشد.',
        '-104': 'ترمینال ارسالی غیرفعال می باشد',
        '-106': 'آدرس آی‌پی درخواستی غیرمجاز می‌باشد.',
    }
    message = result_messages.get(result_code, 'خطای نامشخص')
    logging.error(f"Error: {message}")

def save_payment_to_db(payment_data):
    # Implement the logic to save payment_data to the database
    pass

@retry(wait=wait_fixed(5), stop=stop_after_attempt(3))
def reverse_transaction(payment_data):
    url = 'https://sep.shaparak.ir/verifyTxnRandomSessionkey/ipg/ReverseTransaction'
    data = {
        "RefNum": payment_data.get("RefNum"),
        "TerminalNumber": payment_data.get("TerminalNumber")
    }
    response = requests.post(url, json=data)
    response.raise_for_status()

    response_json = response.json()
    result_code = response_json.get("ResultCode")

    if result_code == '0':
        logging.info("اصلاحیه تراکنش با موفقیت انجام شد")
    else:
        handle_transaction_error(result_code)

if __name__ == '__main__':
    app.run(debug=True)
