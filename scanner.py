def evaluate_open_positions():
    trades = get_active_bought_trades()
    if not trades:
        return

    logger.info(f"Monitoring {len(trades)} active trades")

    for trade in trades:
        try:
            (symbol, entry_price, stop_loss, target1, target2,
             quantity, rr, score, signal_time, setup_type) = trade

            df = get_dhan_data(symbol)
            if df is None:
                continue

            current_price = float(df['close'].iloc[-1])
            ema20 = df['close'].ewm(span=20, adjust=False).mean().iloc[-1]
            rsi = calculate_rsi(df)['rsi'].iloc[-1]
            volume_avg = df['volume'].rolling(window=10).mean().iloc[-1]
            latest_volume = df['volume'].iloc[-1]

            # TARGET 2 HIT
            if current_price >= float(target2):
                send_trade_update(symbol,
                    f"🚀 TARGET 2 HIT\n"
                    f"Stock: {symbol}\n"
                    f"CMP: ₹{round(current_price, 2)}\n"
                    f"Full target achieved. Exit position."
                )
                close_trade(symbol, "TARGET2_HIT", current_price)
                continue

            # TARGET 1 HIT
            if current_price >= float(target1):
                send_trade_update(symbol,
                    f"🎯 TARGET 1 HIT\n"
                    f"Stock: {symbol}\n"
                    f"CMP: ₹{round(current_price, 2)}\n"
                    f"Book 50% position here. Trail rest."
                )
                update_trade_note(symbol, "Target 1 achieved")

            # STOP LOSS HIT
            if current_price <= float(stop_loss):
                send_trade_update(symbol,
                    f"❌ STOP LOSS HIT\n"
                    f"Stock: {symbol}\n"
                    f"CMP: ₹{round(current_price, 2)}\n"
                    f"Trade closed. Accept loss and move on."
                )
                close_trade(symbol, "SL_HIT", current_price)
                continue

            # TRAILING SL
            profit_move = current_price - float(entry_price)
            initial_risk = float(entry_price) - float(stop_loss)

            if profit_move >= (2 * initial_risk):
                new_sl = float(entry_price) + initial_risk
                update_stop_loss(symbol, new_sl)
                send_trade_update(symbol,
                    f"🚀 PROFIT LOCKED\n"
                    f"Stock: {symbol}\n"
                    f"Trailing SL moved to: ₹{round(new_sl, 2)}\n"
                    f"Risk free trade now."
                )
            elif profit_move >= initial_risk:
                update_stop_loss(symbol, float(entry_price))
                send_trade_update(symbol,
                    f"🔒 BREAKEVEN ACTIVATED\n"
                    f"Stock: {symbol}\n"
                    f"SL moved to entry: ₹{round(float(entry_price), 2)}\n"
                    f"No loss possible now."
                )

            # --- SMART NOTIFICATION CONTROL STEP 2 ---
            current_state = "NEUTRAL"

            # INTELLIGENT TRADE ANALYSIS
            price_strength = current_price > ema20
            volume_strength = latest_volume > volume_avg
            momentum_strength = rsi > 55

            if price_strength and volume_strength and momentum_strength:
                current_state = "HEALTHY" # State marked as Healthy
                send_trade_update(symbol,
                    f"📈 TRADE HEALTHY\n"
                    f"Stock: {symbol}\n"
                    f"CMP: ₹{round(current_price, 2)}\n"
                    f"Trend strong above EMA20.\n"
                    f"Volume participation healthy.\n"
                    f"Momentum intact.\n"
                    f"Holding remains valid."
                )
            elif current_price < ema20 or rsi < 48:
                current_state = "WEAKENING" # State marked as Weakening
                send_trade_update(symbol,
                    f"⚠️ MOMENTUM WEAKENING\n"
                    f"Stock: {symbol}\n"
                    f"CMP: ₹{round(current_price, 2)}\n"
                    f"Price losing EMA support.\n"
                    f"Momentum deteriorating.\n"
                    f"Probability of pullback increasing.\n"
                    f"Consider reducing exposure."
                )
            else:
                send_trade_update(symbol,
                    f"⏳ TRADE NEUTRAL\n"
                    f"Stock: {symbol}\n"
                    f"CMP: ₹{round(current_price, 2)}\n"
                    f"Trade active but momentum mixed.\n"
                    f"No strong exit signal yet.\n"
                    f"Wait for confirmation."
                )

        except Exception as e:
            logger.error(f"Trade monitor error for {symbol}: {e}")
