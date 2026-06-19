#!/usr/bin/env python3
from alpaca_trade_api.rest import REST
import os
from dotenv import load_dotenv

load_dotenv()

try:
    api = REST(
        key_id=os.getenv('ALPACA_API_KEY'),
        secret_key=os.getenv('ALPACA_SECRET_KEY'),
        base_url=os.getenv('ALPACA_PAPER_URL')
    )
    account = api.get_account()
    print('SUCCESS: Alpaca connection works!')
    print(f'Account: {account.account_number}')
    print(f'Equity: ${float(account.equity):,.2f}')
    print(f'Cash: ${float(account.cash):,.2f}')
    print(f'Buying Power: ${float(account.buying_power):,.2f}')
except Exception as e:
    print(f'ERROR: {e}')
