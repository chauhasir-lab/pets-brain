def get_live_data(symbol):
    try:
        from fyers_apiv3 import fyersModel
        import os
        
        fyers = fyersModel.FyersModel(
            client_id=os.environ.get("FYERS_APP_ID"),
            token=os.environ.get("FYERS_ACCESS_TOKEN"),
            log_path=""
        )
        
        data = {
            "symbol": f"NSE:{symbol}-EQ",
            "resolution": "5",
            "date_format": "1",
            "range_from": "2024-01-01",
            "range_to": "2024-12-31",
            "cont_flag": "1"
        }
        
        response = fyers.history(data=data)
        
        if response['code'] == 200:
            candles = response['candles']
            df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
            df.set_index('timestamp', inplace=True)
            return df
        else:
            return get_dummy_data(symbol)
            
    except Exception as e:
        logger.error(f"Fyers data error: {e}")
        return get_dummy_data(symbol)
