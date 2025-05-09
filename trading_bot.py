import ccxt
import numpy as np
import requests
import hashlib
import uuid
import time
import json
import random
import discord
from discord.ext import tasks
import matplotlib.pyplot as plt
import os
import mplfinance as mpf
import pandas as pd
from discord.ext import commands


# === 全域變數與統計檔案設定 ===
STATS_FILE = "stats.json"
win_count = 0
loss_count = 0

def load_stats():
    global win_count, loss_count
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE, 'r') as f:
                stats = json.load(f)
                win_count = stats.get('win_count', 0)
                loss_count = stats.get('loss_count', 0)
            print(f"已載入統計數據: 勝場 {win_count}, 敗場 {loss_count}")
        except (IOError, json.JSONDecodeError) as e:
            print(f"讀取統計數據失敗: {e}, 初始化為 0")
            win_count = 0
            loss_count = 0
    else:
        print("未找到統計數據檔案，初始化為 0")
        win_count = 0
        loss_count = 0

def save_stats():
    global win_count, loss_count
    try:
        with open(STATS_FILE, 'w') as f:
            json.dump({'win_count': win_count, 'loss_count': loss_count}, f)
        print(f"已儲存統計數據: 勝場 {win_count}, 敗場 {loss_count}")
    except IOError as e:
        print(f"錯誤：無法儲存勝率統計數據: {e}")

# === Bitunix API 函數 === #
def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode('utf-8')).hexdigest()


# 完全按照ccc.py中的get_signed_params函數實現

from config import BITUNIX_API_KEY, BITUNIX_SECRET_KEY,N, DISCORD_WEBHOOK_URL

def get_signed_params(api_key, secret_key, query_params: dict = None, body: dict = None, path: str = None, method: str = None):
    """
    按照 Bitunix 官方雙重 SHA256 簽名方式對請求參數進行簽名。
    
    參數:
        api_key (str): 用戶 API Key
        secret_key (str): 用戶 Secret Key
        query_params (dict): 查詢參數 (GET 方法)
        body (dict or None): 請求 JSON 主體 (POST 方法)
    
    返回:
        headers (dict): 包含簽名所需的請求頭（api-key, sign, nonce, timestamp 等）
    """
    nonce = uuid.uuid4().hex
    timestamp = str(int(time.time() * 1000))

    # 構造 query string: 將參數按鍵名 ASCII 升序排序後，鍵名與鍵值依次拼接
    if query_params:
        params_str = {k: str(v) for k, v in query_params.items()}
        sorted_items = sorted(params_str.items(), key=lambda x: x[0])
        query_str = "".join([f"{k}{v}" for k, v in sorted_items])
    else:
        query_str = ""

    # 構造 body string: 將 JSON 體壓縮成字符串 (無空格)
    if body is not None:
        if isinstance(body, (dict, list)):
            body_str = json.dumps(body, separators=(',', ':'), ensure_ascii=False)
        else:
            body_str = str(body)
    else:
        body_str = ""

    # 根據 method 決定簽名內容
    if method == "GET":
        digest_input = nonce + timestamp + api_key + query_str
    else:
        digest_input = nonce + timestamp + api_key + body_str
    # 第一次 SHA256
    digest = hashlib.sha256(digest_input.encode('utf-8')).hexdigest()
    # 第二次 SHA256
    sign = hashlib.sha256((digest + secret_key).encode('utf-8')).hexdigest()

  

    # 構造標頭
    headers = {
        "api-key": api_key,
        "sign": sign,
        "nonce": nonce,
        "timestamp": timestamp,
        "language": "en-US",
        "Content-Type": "application/json"
    }
    return nonce, timestamp, sign, headers

def send_order(api_key, secret_key, symbol, margin_coin, side, size, leverage=20, position_id=None):
    # 直接下單，不再自動設置槓桿/槓桿
    # 正確的API端點路徑
    path = "/api/v1/futures/trade/place_order"
    url = f"https://fapi.bitunix.com{path}"
    
    # 根據cc.py中的格式調整請求參數
    # 將side轉換為適當的side和tradeSide參數
    if side == "open_long":
        api_side = "BUY"
        trade_side = "OPEN"
    elif side == "close_long":
        api_side = "SELL"
        trade_side = "CLOSE"
    elif side == "open_short":
        api_side = "SELL"
        trade_side = "OPEN"
    elif side == "close_short":
        api_side = "BUY"
        trade_side = "CLOSE"
    else:
        print(f"錯誤：不支持的交易方向 {side}")
        return {"error": f"不支持的交易方向: {side}"}
    
    body = {
        "symbol": symbol,
        "marginCoin": margin_coin,  # 新增保證金幣種參數
        "qty": str(size),  # API要求數量為字符串
        "side": api_side,
        "tradeSide": trade_side,
        "orderType": "MARKET",  # 市價單
        "effect": "GTC"  # 訂單有效期
    }

    if position_id and (side == "close_long" or side == "close_short"):
        body["positionId"] = position_id

    print(f"準備發送訂單: {body}")
    
    try:
        # 使用更新後的get_signed_params獲取完整的headers
        _, _, _, headers = get_signed_params(BITUNIX_API_KEY, BITUNIX_SECRET_KEY, {}, body)
        
        response = requests.post(url, headers=headers, data=json.dumps(body, separators=(',', ':'), ensure_ascii=False))
        response.raise_for_status()  # 檢查HTTP錯誤
        result = response.json()
        print(f"API響應: {result}")
        return result
    except requests.exceptions.HTTPError as e:
        error_msg = f"HTTP錯誤: {e}, 響應: {response.text if 'response' in locals() else '無響應'}"
        print(error_msg)
        send_discord_message(f"🔴 **下單錯誤**: {error_msg} 🔴", api_key, secret_key)
        return {"error": error_msg}
    except requests.exceptions.RequestException as e:
        error_msg = f"請求錯誤: {e}"
        print(error_msg)
        send_discord_message(f"🔴 **下單錯誤**: {error_msg} 🔴", api_key, secret_key)
        return {"error": error_msg}
    except Exception as e:
        error_msg = f"未知錯誤: {e}"
        print(error_msg)
        send_discord_message(f"🔴 **下單錯誤**: {error_msg} 🔴", api_key, secret_key)
        return {"error": error_msg}


# === Discord 提醒設定 === #
# DISCORD_WEBHOOK_URL = 'https://discordapp.com/api/webhooks/1366780723864010813/h_CPbJX3THcOElVVHYOeJPR4gTgZGHJ1ehSeXuOAceGTNz3abY0XlljPzzxkaimAcE77'

# 消息緩衝區和計時器設置
message_buffer = []
last_send_time = 0
BUFFER_TIME_LIMIT = 180  # 3分鐘 = 180秒

# 記錄上一次的餘額，用於比較變化
last_balance = None

# 修改函數簽名以包含 operation_details
def send_discord_message(core_message, api_key=None, secret_key=None, symbol="ETHUSDT", operation_details=None):
    global message_buffer, last_send_time, win_count, loss_count # 確保能訪問全域勝敗計數
    current_time = time.time()

    # 獲取最新的實際持倉狀態和PNL (用於顯示"目前持倉"的盈虧)
    actual_pos_side, actual_pos_qty_str, _, actual_unrealized_pnl = None, None, None, 0.0
    current_pos_pnl_msg = ""
    
    if api_key and secret_key:
        # 注意：這裡的 get_current_position_details 返回四個值
        actual_pos_side, actual_pos_qty_str, _, actual_unrealized_pnl = get_current_position_details(api_key, secret_key, symbol)
        if actual_pos_side in ["long", "short"] and actual_unrealized_pnl is not None:
            # 這裡可以加入收益率計算，如果 get_current_position_details 也返回保證金的話
            current_pos_pnl_msg = f"\n💰 目前未實現盈虧: {actual_unrealized_pnl:.4f} USDT"

    # 構造勝率字符串
    total_trades = win_count + loss_count
    win_rate_str = f"{win_count / total_trades * 100:.2f}% ({win_count}勝/{loss_count}負)" if total_trades > 0 else "N/A (尚無已完成交易)"
    
    action_specific_msg = core_message
    current_pos_status_for_discord = ""

    if operation_details:
        op_type = operation_details.get("type")
        if op_type == "close_success":
            side_closed_display = "多單" if operation_details.get("side_closed") == "long" else "空單"
            closed_qty = operation_details.get("qty", "N/A")
            pnl = operation_details.get("pnl", 0.0)
            pnl_display = f"{pnl:.4f}" if pnl is not None else "N/A"
            action_specific_msg = f"{core_message} (數量: {closed_qty})\n🎯 **平倉類型**: {side_closed_display}\n💰 **本次已實現盈虧**: {pnl_display} USDT"
            current_pos_status_for_discord = "🔄 **目前持倉**：無持倉" # 平倉成功後，假設無持倉
            current_pos_pnl_msg = "" # 平倉後，不顯示“目前未實現盈虧”
        elif op_type == "open_success":
            side_opened_display = "多單" if operation_details.get("side_opened") == "long" else "空單"
            opened_qty = operation_details.get("qty", "N/A")
            entry_price_display = f"{operation_details.get('entry_price', 'N/A'):.2f}"
            action_specific_msg = f"{core_message} (數量: {opened_qty}, 估計價格: {entry_price_display} USDT)\nℹ️ **開倉類型**: {side_opened_display}"
            # 開倉後，持倉狀態應由下方的 actual_pos_side 決定
        elif op_type == "error":
            action_specific_msg = f"🔴 **錯誤**: {core_message}\n{operation_details.get('details', '')}"
        elif op_type == "balance_update": # 用於餘額更新
             action_specific_msg = core_message # core_message 已經是餘額信息
        elif op_type == "status_update": # 用於通道指標等狀態更新
            action_specific_msg = core_message
        # 可以添加更多 op_type 的處理

    # 決定最終的持倉狀態顯示 (如果不是平倉成功，則根據實際查詢結果)
    if not (operation_details and operation_details.get("type") == "close_success"):
        if actual_pos_side == "long":
            current_pos_status_for_discord = f"📈 **目前持倉**：多單 (數量: {actual_pos_qty_str})"
        elif actual_pos_side == "short":
            current_pos_status_for_discord = f"📉 **目前持倉**：空單 (數量: {actual_pos_qty_str})"
        else:
            current_pos_status_for_discord = "🔄 **目前持倉**：無持倉"

    # 組合最終訊息
    full_message = f"{action_specific_msg}\n\n📊 **交易統計**：{win_rate_str}\n{current_pos_status_for_discord}{current_pos_pnl_msg}"
    
    # 在訊息開頭和結尾添加分隔線
    full_message = "\n--------------------------------\n" + full_message + "\n--------------------------------\n"

    message_buffer.append(full_message)
    if current_time - last_send_time >= BUFFER_TIME_LIMIT or \
       (len(message_buffer) == 1 and last_send_time == 0) or \
       (operation_details and operation_details.get("force_send", False)): # 新增強制發送選項
        combined_message = "\n\n".join(message_buffer)
        data_payload = {"content": combined_message}
        
        # 檢查是否有圖片需要發送 (來自 operation_details)
        files_to_send = None
        if operation_details and "image_path" in operation_details:
            try:
                # 這裡需要確保 operation_details["image_path"] 是一個已經打開的檔案對象或路徑
                # 如果是路徑，需要在這裡打開
                # 為了簡化，假設 plot_channel_and_send_to_discord 會處理檔案的打開和關閉，並直接傳遞 files dict
                if "files_data" in operation_details: # 假設 files_data 是 {'file': file_object}
                     files_to_send = operation_details["files_data"]
                     # 注意：如果傳遞 files_data，requests 的 data 參數需要是 dict，而不是 json.dumps
                     requests.post(DISCORD_WEBHOOK_URL, data=data_payload, files=files_to_send)
                     if hasattr(files_to_send['file'], 'close'): # 關閉檔案，如果它是被打開的
                         files_to_send['file'].close()
                     if os.path.exists(operation_details["image_path"]): # 刪除圖片
                         os.remove(operation_details["image_path"])

                else: # 如果沒有 files_data，則正常發送 JSON
                    requests.post(DISCORD_WEBHOOK_URL, json=data_payload)

            except Exception as e:
                print(f"發送 Discord 訊息 (帶圖片) 失敗: {e}")
                # 嘗試不帶圖片發送
                requests.post(DISCORD_WEBHOOK_URL, json=data_payload)
        else:
            requests.post(DISCORD_WEBHOOK_URL, json=data_payload)
            
        message_buffer = []
        last_send_time = current_time
        print(f"已發送合併消息 - 時間: {time.strftime('%Y-%m-%d %H:%M:%S')}")

# 強制發送緩衝區中的所有消息，不管時間限制
def flush_discord_messages():
    global message_buffer, last_send_time
    
    if message_buffer:
        # 強制發送時，我們沒有特定的 operation_details，所以它會按常規方式組合訊息
        # 但如果最後一條消息有圖片，這裡的邏輯需要更複雜，或者假設 flush 不處理圖片
        combined_message = "\n\n".join(message_buffer)
        data = {
            "content": combined_message
        }
        requests.post(DISCORD_WEBHOOK_URL, json=data)
        message_buffer = []
        last_send_time = time.time() # 更新發送時間
        print(f"已強制發送緩衝區消息 - 時間: {time.strftime('%Y-%m-%d %H:%M:%S')}")


# === 策略邏輯 === #
def fetch_ohlcv(trading_pair):
    # 使用ccxt庫連接到Binance交易所
    exchange = ccxt.binance()
    # 獲取指定交易對的4小時K線數據，限制為最近100根
    # 這將確保我們總是獲取最新的市場數據
    ohlcv = exchange.fetch_ohlcv(trading_pair, timeframe='1h', limit=100)
    return np.array(ohlcv)


def compute_channels(ohlcv, N):
    high = ohlcv[:, 2]
    low = ohlcv[:, 3]
    close = ohlcv[:, 4]

    upperBand = np.full_like(close, np.nan)
    lowerBand = np.full_like(close, np.nan)
    middleBand = np.full_like(close, np.nan)

    for i in range(N, len(close)):
        # 計算上軌：若當前 4 小時的最低價比昨天的最低價低，則取過去 N 根 K 線的最高價
        if low[i] < low[i - 1]:
            upperBand[i] = np.max(high[i - N:i])
        else:
            upperBand[i] = upperBand[i - 1]

        # 計算下軌：若當前 4 小時的最高價比昨天的最高價高，則取過去 N 根 K 線的最低價
        if high[i] > high[i - 1]:
            lowerBand[i] = np.min(low[i - N:i])
        else:
            lowerBand[i] = lowerBand[i - 1]

        # 計算中軌
        middleBand[i] = (upperBand[i] + lowerBand[i]) / 2

    return upperBand, lowerBand, middleBand, close


# === 主邏輯 === #
# 全局變量，用於存儲當前錢包餘額
current_wallet_balance = 0.0

def check_wallet_balance(api_key, secret_key):
    global last_balance, current_wallet_balance
    margin_coin = "USDT"
    query_params = {"marginCoin": margin_coin}
    path = "/api/v1/futures/account"
    url = f"https://fapi.bitunix.com{path}?marginCoin={margin_coin}"
    
    # 使用更新後的get_signed_params獲取完整的headers，指定method為GET
    _, _, _, headers = get_signed_params(api_key, secret_key, query_params, method="GET")

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()  # Check if request was successful

        # Log the full response for debugging
        print(f"Response from API: {response.text}")

        balance_info = response.json()
        current_balance = None

        # Check if 'data' is in the response
        if "data" in balance_info and balance_info["data"] is not None:
            print(f"完整的數據結構: {balance_info['data']}")
            if isinstance(balance_info["data"], dict) and "available" in balance_info["data"]:
                balance = balance_info["data"]["available"]
                if isinstance(balance, dict) and "USDT" in balance:
                    current_balance = float(balance['USDT'])
                    if last_balance is None or current_balance != last_balance:
                        send_discord_message(
                            f"💰 **當前餘額**: {current_balance:.4f} USDT 💰",  # 假設是 USDT
                            api_key, secret_key, symbol=TRADING_PAIR.split('/')[0] + "USDT", # 從 config 或其他地方獲取 symbol
                            operation_details={"type": "balance_update", "force_send": True}
                        )
                        print(f"餘額已變動: {last_balance} -> {current_balance}")
                    else:
                        print(f"餘額未變動: {current_balance} USDT")
                else:
                    try:
                        current_balance = float(balance)
                    except (ValueError, TypeError):
                        current_balance = 0.0
                    if last_balance is None or current_balance != last_balance:
                        send_discord_message(f"💰 **當前餘額**: {current_balance} 💰", api_key, secret_key)
                        print(f"餘額已變動: {last_balance} -> {current_balance}")
                    else:
                        print(f"餘額未變動: {current_balance}")
            else:
                try:
                    current_balance = float(balance_info['data'])
                except (ValueError, TypeError):
                    current_balance = 0.0
                if last_balance is None or current_balance != last_balance:
                    send_discord_message(f"💼 **餘額信息**: {current_balance} 💼", api_key, secret_key)
                    print(f"餘額信息已變動: {last_balance} -> {current_balance}")
                else:
                    print(f"餘額信息未變動: {current_balance}")

            last_balance = current_balance
            current_wallet_balance = current_balance # 確保全域變數被更新
            return current_balance
        else:
            error_message = balance_info.get("message", "無法獲取餘額信息")
            send_discord_message(f"⚠️ **餘額查詢錯誤**: {error_message} ⚠️", api_key, secret_key,
                operation_details={"type": "error", "details": f"Balance check failed: {error_message}", "force_send": True}
            )
            return current_wallet_balance # 返回上一次的餘額或初始值
    except requests.exceptions.HTTPError as err:
        print(f"HTTP Error: {err}")
        send_discord_message(f"🔴 **餘額查詢HTTP錯誤**: {err} 🔴", api_key, secret_key, operation_details={"type": "error", "details": str(err), "force_send": True})
        return current_wallet_balance
    except requests.exceptions.RequestException as err:
        print(f"Request Exception: {err}")
        send_discord_message(f"🔴 **餘額查詢請求錯誤**: {err} 🔴", api_key, secret_key, operation_details={"type": "error", "details": str(err), "force_send": True})
        return current_wallet_balance

# === 查詢持倉狀態 === #
def get_current_position_details(api_key, secret_key, symbol, margin_coin="USDT"):
    """查詢目前持倉的詳細信息，包括方向、數量、positionId 和未實現盈虧。"""
    import hashlib, uuid, time, requests

    url = "https://fapi.bitunix.com/api/v1/futures/position/get_pending_positions"
    params = {"symbol": symbol}
    nonce = uuid.uuid4().hex
    timestamp = str(int(time.time() * 1000))
    
    sorted_items = sorted((k, str(v)) for k, v in params.items())
    query_string = "".join(f"{k}{v}" for k, v in sorted_items)

    digest_input = nonce + timestamp + api_key + query_string
    digest = hashlib.sha256(digest_input.encode('utf-8')).hexdigest()
    sign = hashlib.sha256((digest + secret_key).encode('utf-8')).hexdigest()

    headers = {
        "api-key": api_key,
        "sign": sign,
        "nonce": nonce,
        "timestamp": timestamp,
        "Content-Type": "application/json"
    }
    try:
        res = requests.get(url, headers=headers, params=params)
        data = res.json()
        if data.get("code") == 0 and data.get("data"):
            for pos_detail in data["data"]:
                pos_qty_str = pos_detail.get("qty", "0")
                position_id = pos_detail.get("positionId")
                unrealized_pnl = float(pos_detail.get("unrealizedPNL", 0.0)) # 獲取未實現盈虧
                
                if float(pos_qty_str) > 0: # 只處理有實際數量的倉位
                    if pos_detail.get("side") == "BUY":
                        print(f"API偵測到多單持倉: qty={pos_qty_str}, positionId={position_id}, PNL={unrealized_pnl}")
                        return "long", pos_qty_str, position_id, unrealized_pnl
                    if pos_detail.get("side") == "SELL":
                        print(f"API偵測到空單持倉: qty={pos_qty_str}, positionId={position_id}, PNL={unrealized_pnl}")
                        return "short", pos_qty_str, position_id, unrealized_pnl
        # print("API未偵測到有效持倉或回傳數據格式問題。") # 可以根據需要取消註釋
        return None, None, None, 0.0  # 無持倉或錯誤，PNL返回0.0
    except Exception as e:
        print(f"查詢持倉詳細失敗: {e}")
        return None, None, None, 0.0

order_points = []  # 全域下單點記錄

def plot_channel_and_send_to_discord(ohlcv, upperBand, lowerBand, middleBand, last, message, order_points=None):
    import mplfinance as mpf
    import pandas as pd
    import numpy as np
    import os

    print("DEBUG: order_points 傳入內容：", order_points)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('datetime', inplace=True)
    df = df[['open', 'high', 'low', 'close', 'volume']]

    apds = [
        mpf.make_addplot(upperBand, color='#00FFFF', width=1.2),
        mpf.make_addplot(lowerBand, color='#FFFF00', width=1.2),
        mpf.make_addplot(middleBand, color='#FF00FF', width=1.0, linestyle='dashed')
    ]

    def mark_orders(ax):
        if order_points:
            for pt in order_points:
                print("DEBUG: 標註點", pt)
                if 0 <= pt['idx'] < len(df):
                    dt = df.index[pt['idx']]
                    price = pt['price']
                    color = '#39FF14' if pt['side'] == 'long' else '#FF1744'  # 螢光綠/亮紅
                    marker = '^' if pt['side'] == 'long' else 'v'
                    offset = -40 if pt['side'] == 'long' else 40
                    ax.scatter(dt, price, color=color, marker=marker, s=400, zorder=10, edgecolors='black', linewidths=2)
                    ax.annotate(
                        f"{pt['side'].upper()}",
                        (dt, price),
                        textcoords="offset points",
                        xytext=(0, offset),
                        ha='center',
                        color=color,
                        fontsize=16,
                        fontweight='bold',
                        bbox=dict(boxstyle='round,pad=0.4', fc='black', ec=color, lw=3, alpha=0.95),
                        arrowprops=dict(arrowstyle='->', color=color, lw=3, alpha=0.8)
                    )

    img_path = 'channel_candle.png'
    fig, axlist = mpf.plot(
        df,
        type='candle',
        style='charles',
        addplot=apds,
        figsize=(16, 8),
        title='通道指標蠟燭圖',
        ylabel='價格',
        returnfig=True,
        tight_layout=True,
        update_width_config=dict(candle_linewidth=1.2, candle_width=0.6)
    )
    mark_orders(axlist[0])
    fig.savefig(img_path, facecolor='black')
    with open(img_path, 'rb') as f:
        files = {'file': f}
        data = {"content": message}
        requests.post(DISCORD_WEBHOOK_URL, data=data, files=files)
    os.remove(img_path)

def main():
    global win_count, loss_count # 宣告使用全域變數
    load_stats() # 啟動時載入統計數據

    # 用戶參數
    from config import TRADING_PAIR, SYMBOL, MARGIN_COIN, LEVERAGE, WALLET_PERCENTAGE, N
    api_key = "b29c2647926baeafaccd04558dd78fc5"
    secret_key = "52ac11f07679ed99f5a068dbd7c54744"
    trading_pair = TRADING_PAIR
    symbol = SYMBOL
    margin_coin = "USDT"
    leverage = LEVERAGE
    wallet_percentage = WALLET_PERCENTAGE
    N = N
    current_pos_side = None
    current_pos_qty = None
    win_count = 0
    loss_count = 0
    last_upper_band = None
    last_lower_band = None
    last_middle_band = None
    
    print("交易機器人啟動，開始載入初始K線數據...")
    send_discord_message("🚀 **交易機器人啟動** 🚀\n📊 開始載入初始K線數據... 📊", api_key, secret_key, symbol, operation_details={"type": "info", "force_send": True})

    ohlcv = fetch_ohlcv(trading_pair)
    if not ohlcv.any(): # 檢查 ohlcv 是否為空或無效
        send_discord_message("🔴 啟動失敗：無法獲取初始K線數據，請檢查網路或API設置。", api_key, secret_key, symbol, operation_details={"type": "error", "details": "Failed to fetch initial K-line data", "force_send": True})
        return
    
    upperBand, lowerBand, middleBand, close = compute_channels(ohlcv, N)
    last = len(close) - 1
    last_kline_len = len(ohlcv)

    # 在主循環開始前，獲取一次當前持倉狀態 (返回四個值)
    current_pos_side, current_pos_qty_str, current_pos_id, current_unrealized_pnl = get_current_position_details(api_key, secret_key, symbol)
    print(f"啟動時持倉狀態: side={current_pos_side}, qty={current_pos_qty_str}, positionId={current_pos_id}, PNL={current_unrealized_pnl}")
    
    # 啟動時自動補上現有持倉點 (這部分邏輯如果存在，需要確保 order_points 的更新)
    import numpy as np
    from typing import Any
    def get_entry_price_and_side(api_key: str, secret_key: str, symbol: str) -> Any:
        url = "https://fapi.bitunix.com/api/v1/futures/position/get_pending_positions"
        params = {"symbol": symbol}
        nonce = uuid.uuid4().hex
        timestamp = str(int(time.time() * 1000))
        api_key_ = api_key
        secret_key_ = secret_key
        sorted_items = sorted((k, str(v)) for k, v in params.items())
        query_string = "".join(f"{k}{v}" for k, v in sorted_items)
        digest_input = nonce + timestamp + api_key_ + query_string
        digest = hashlib.sha256(digest_input.encode('utf-8')).hexdigest()
        sign = hashlib.sha256((digest + secret_key_).encode('utf-8')).hexdigest()
        headers = {
            "api-key": api_key_,
            "sign": sign,
            "nonce": nonce,
            "timestamp": timestamp,
            "Content-Type": "application/json"
        }
        try:
            res = requests.get(url, headers=headers, params=params)
            data = res.json()
            if data.get("code") == 0 and data.get("data"):
                for pos in data["data"]:
                    side = None
                    if pos.get("side") == "BUY" and float(pos.get("qty", 0)) > 0:
                        side = "long"
                    elif pos.get("side") == "SELL" and float(pos.get("qty", 0)) > 0:
                        side = "short"
                    if side:
                        entry_price = float(pos.get("avgOpenPrice", pos.get("entryValue", 0)))
                        return entry_price, side
            return None
        except Exception as e:
            print(f"查詢持倉失敗: {e}")
            return None

    entry = get_entry_price_and_side(api_key, secret_key, symbol)
    if entry:
        entry_price, side = entry
        idx = int(np.argmin(np.abs(close - entry_price)))
        order_points.append({'idx': idx, 'price': close[idx], 'side': side})
        print(f"DEBUG: 啟動自動補標註現有持倉點: {order_points[-1]}")

    while True:
        # 檢查錢包餘額並獲取當前餘額
        balance = check_wallet_balance(api_key, secret_key)
        # 計算下單數量 (錢包餘額的30%*槓桿/當前BTC價格)
        btc_price = None
        # 每次循環都重新獲取最新的K線數據
        print("獲取最新K線數據...")
        ohlcv = fetch_ohlcv(trading_pair)
        print(f"成功獲取 {len(ohlcv)} 根K線數據")
        upperBand, lowerBand, middleBand, close = compute_channels(ohlcv, N)
        btc_price = close[-1] if len(close) > 0 else 0
        if btc_price > 0:
            size = round(balance * wallet_percentage * leverage / btc_price, 6)
        else:
            size = 0
        print(f"當前餘額: {balance} USDT, 下單數量: {size} ETH (錢包的{wallet_percentage*100}%*槓桿{leverage}/ETH價格{btc_price})")
        
        if size <= 0:
            print("餘額為0，退出程序")
            send_discord_message("🛑 **程序終止**: 餘額為0，交易機器人已停止運行 🛑", api_key, secret_key)
            # 在退出前強制發送所有緩衝區中的消息
            flush_discord_messages()
            print("程序已終止運行")
            return  # 直接退出main函數而不是繼續循環
        
        # 查詢實際持倉狀態
        current_pos_side, current_pos_qty_str, current_pos_id, current_unrealized_pnl = get_current_position_details(api_key, secret_key, symbol) # Updated, added current_pos_id and current_unrealized_pnl
        print(f"實際持倉狀態: side={current_pos_side}, qty={current_pos_qty_str}") # Updated
        
        # ====== 補回 channel_changed 判斷與通道變動通知 ======
        # 每次循環都重新獲取最新的K線數據
        print("獲取最新K線數據...")
        ohlcv = fetch_ohlcv(trading_pair)
        print(f"成功獲取 {len(ohlcv)} 根K線數據")
        upperBand, lowerBand, middleBand, close = compute_channels(ohlcv, N)

        last = -1  # 最新一根 K 線
        print("最新收盤價:", close[last])
        print("上軌:", upperBand[last], "下軌:", lowerBand[last], "中軌:", middleBand[last])

        # 檢查通道值是否發生變化
        channel_changed = False

        # 首次運行時初始化上一次的通道值
        if last_upper_band is None or last_lower_band is None or last_middle_band is None:
            channel_changed = True
        # 檢查通道值是否有變化
        elif (abs(upperBand[last] - last_upper_band) > 0.001 or 
              abs(lowerBand[last] - last_lower_band) > 0.001 or 
              abs(middleBand[last] - last_middle_band) > 0.001):
            channel_changed = True

        # 更新上一次的通道值
        last_upper_band = upperBand[last]
        last_lower_band = lowerBand[last]
        last_middle_band = middleBand[last]

        # 只有當通道值發生變化時才發送Discord通知
        if channel_changed:
            plot_channel_and_send_to_discord(
                ohlcv, upperBand, lowerBand, middleBand, last,
                f"📢 **通道指標變動通知** 📢\n"
                f"📈 最新收盤價: ${close[last]:,.2f}\n"
                f"⬆️ 上軌: ${upperBand[last]:,.2f}\n"
                f"⬇️ 下軌: ${lowerBand[last]:,.2f}\n"
                f"➖ 中軌: ${middleBand[last]:,.2f}\n"
                f"🕒 更新時間: {time.strftime('%Y-%m-%d %H:%M:%S')}",
                order_points=order_points
            )
            print(f"通道指標已變動 - 時間: {time.strftime('%Y-%m-%d %H:%M:%S')}")

        print(f"通道指標狀態 - 時間: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"上軌: {upperBand[last]}, 中軌: {middleBand[last]}, 下軌: {lowerBand[last]}")
        print(f"當前收盤價: {close[last]}")
        # ====== 補回結束 ======
        
        if current_pos_side is None: # Changed from 'position'
            if close[last] > upperBand[last]:
                print(">> 訊號：開多單")
                result = send_order(api_key, secret_key, symbol, margin_coin, "open_long", size, leverage)
                print("下單結果:", result)
                if "error" in result:
                    error_msg = result.get("error", "未知錯誤")
                    print(f"開多單失敗: {error_msg}")
                    send_discord_message(f"⚠️ **開多單失敗**: {error_msg} ⚠️", api_key, secret_key)
                elif result.get("code", -1) == 0:
                    current_pos_side = 'long' # Changed from position = 'long'
                    # current_pos_qty_str will be updated by get_current_position_details in the next loop
                    order_points.append({'idx': len(close)-1, 'price': close[-1], 'side': 'long'})
                    print("DEBUG: 新增多單 order_point:", order_points[-1])
                    send_discord_message("🔵 **開倉成功**: 多單 📈", api_key, secret_key)
                else:
                    error_msg = result.get("msg", "API返回錯誤")
                    print(f"開多單API錯誤: {error_msg}")
                    send_discord_message(f"⚠️ **開多單API錯誤**: {error_msg} ⚠️", api_key, secret_key)
                    
            elif close[last] < lowerBand[last]:
                print(">> 訊號：開空單")
                result = send_order(api_key, secret_key, symbol, margin_coin, "open_short", size, leverage)
                print("下單結果:", result)
                if "error" in result:
                    error_msg = result.get("error", "未知錯誤")
                    print(f"開空單失敗: {error_msg}")
                    send_discord_message(f"⚠️ **開空單失敗**: {error_msg} ⚠️", api_key, secret_key)
                elif result.get("code", -1) == 0:
                    current_pos_side = 'short' # Changed from position = 'short'
                    # current_pos_qty_str will be updated by get_current_position_details in the next loop
                    order_points.append({'idx': len(close)-1, 'price': close[-1], 'side': 'short'})
                    print("DEBUG: 新增空單 order_point:", order_points[-1])
                    send_discord_message("🔴 **開倉成功**: 空單 📉", api_key, secret_key)
                else:
                    error_msg = result.get("msg", "API返回錯誤")
                    print(f"開空單API錯誤: {error_msg}")
                    send_discord_message(f"⚠️ **開空單API錯誤**: {error_msg} ⚠️", api_key, secret_key)
            else:
                print(">> 沒有訊號")
                
        elif current_pos_side == 'long' and close[last] < middleBand[last]: # Changed from 'position'
            print(">> 平多條件成立，執行平倉")
            if current_pos_qty_str and float(current_pos_qty_str) > 0:
                result = send_order(api_key, secret_key, symbol, margin_coin, "close_long", current_pos_qty_str, leverage, position_id=current_pos_id) # Use current_pos_qty_str
                print("平倉結果:", result)
            
                # 檢查平倉結果
                if "error" in result:
                    error_msg = result.get("error", "未知錯誤")
                    print(f"平多單失敗: {error_msg}")
                    send_discord_message(f"⚠️ **平多單失敗**: {error_msg} ⚠️", api_key, secret_key)
                elif result.get("code", -1) == 0:
                    current_pos_side = None # Changed from position = None
                    current_pos_qty_str = "0" # Update local state
                    win_count += 1
                    send_discord_message(f"✅ **平倉成功**: 多單 📈\n🏆 勝率: {win_count / (win_count + loss_count) * 100:.2f}%", api_key, secret_key)
                else:
                    error_msg = result.get("msg", "API返回錯誤")
                    print(f"平多單API錯誤: {error_msg}")
                    send_discord_message(f"⚠️ **平多單API錯誤**: {error_msg} ⚠️", api_key, secret_key)
            else:
                print(f">> 嘗試平多倉，但查詢到的持倉數量為 {current_pos_qty_str}。不執行平倉。")
                send_discord_message(f"⚠️ **平多單警告**: 嘗試平倉但查詢到的持倉數量為 {current_pos_qty_str}。 ⚠️", api_key, secret_key)
                
        elif current_pos_side == 'short' and close[last] > middleBand[last]: # Changed from 'position'
            print(">> 平空條件成立，執行平倉")
            if current_pos_qty_str and float(current_pos_qty_str) > 0:
                result = send_order(api_key, secret_key, symbol, margin_coin, "close_short", current_pos_qty_str, leverage, position_id=current_pos_id) # Use current_pos_qty_str
                print("平倉結果:", result)
            
                # 檢查平倉結果
                if "error" in result:
                    error_msg = result.get("error", "未知錯誤")
                    print(f"平空單失敗: {error_msg}")
                    send_discord_message(f"⚠️ **平空單失敗**: {error_msg} ⚠️", api_key, secret_key)
                elif result.get("code", -1) == 0:
                    current_pos_side = None # Changed from position = None
                    current_pos_qty_str = "0" # Update local state
                    win_count += 1
                    send_discord_message(f"✅ **平倉成功**: 空單 📉\n🏆 勝率: {win_count / (win_count + loss_count) * 100:.2f}%", api_key, secret_key)
                else:
                    error_msg = result.get("msg", "API返回錯誤")
                    print(f"平空單API錯誤: {error_msg}")
                    send_discord_message(f"⚠️ **平空單API錯誤**: {error_msg} ⚠️", api_key, secret_key)
            else:
                print(f">> 嘗試平空倉，但查詢到的持倉數量為 {current_pos_qty_str}。不執行平倉。")
                send_discord_message(f"⚠️ **平空單警告**: 嘗試平倉但查詢到的持倉數量為 {current_pos_qty_str}。 ⚠️", api_key, secret_key)
        else:
            print(">> 持倉中，尚未達到平倉條件")

        # ===== 新增：有新K線時自動發送圖表 =====
        if len(ohlcv) > last_kline_len:
            last = len(close) - 1
            plot_channel_and_send_to_discord(
                ohlcv, upperBand, lowerBand, middleBand, last,
                f"🆕 新K線產生，最新收盤價: ${close[last]:,.2f}\n"
                f"⬆️ 上軌: ${upperBand[last]:,.2f}\n"
                f"⬇️ 下軌: ${lowerBand[last]:,.2f}\n"
                f"➖ 中軌: ${middleBand[last]:,.2f}\n"
                f"🕒 時間: {time.strftime('%Y-%m-%d %H:%M:%S')}",
                order_points=order_points
            )
            print("已自動發送新K線圖表通知")
        last_kline_len = len(ohlcv)
        # ===== 新增結束 =====

        # 休眠5分鐘後再次獲取最新數據並更新通道指標
        next_update_time = time.strftime('%H:%M:%S', time.localtime(time.time() + 60 * 5))
        print(f"休眠中，將在 {next_update_time} 再次更新市場數據和通道指標...")
        # 在休眠前強制發送所有緩衝區中的消息
        flush_discord_messages()
        time.sleep(60)  # 每 5 分鐘檢查一次


if __name__ == "__main__":
    try:
        main()
    finally:
        # 確保程序結束時發送所有緩衝區中的消息
        flush_discord_messages()


def send_profit_loss_to_discord(api_key, secret_key, symbol, message):
    position = get_current_position(api_key, secret_key, symbol)
    if position in ['long', 'short']:
        url = "https://fapi.bitunix.com/api/v1/futures/position/get_pending_positions"
        params = {"symbol": symbol}
        nonce = uuid.uuid4().hex
        timestamp = str(int(time.time() * 1000))
        digest_input = nonce + timestamp + api_key + "symbol" + symbol
        digest = hashlib.sha256(digest_input.encode('utf-8')).hexdigest()
        sign = hashlib.sha256((digest + secret_key).encode('utf-8')).hexdigest()
        headers = {
            "api-key": api_key,
            "sign": sign,
            "nonce": nonce,
            "timestamp": timestamp,
            "Content-Type": "application/json"
        }
        try:
            res = requests.get(url, headers=headers, params=params)
            data = res.json()
            if data.get("code") == 0 and data.get("data"):
                for pos in data["data"]:
                    if ((position == "long" and pos.get("side") == "BUY") or
                        (position == "short" and pos.get("side") == "SELL")):
                        pnl = float(pos.get("unrealizedPNL", 0))
                        margin = float(pos.get("margin", 0))
                        if margin:
                            profit_pct = (pnl / margin) * 100
                            message += f"\n💰 盈虧: {pnl:.4f} USDT｜收益率: {profit_pct:.2f}%"
                        else:
                            message += f"\n💰 盈虧: {pnl:.4f} USDT"
        except Exception as e:
            message += f"\n查詢盈虧失敗: {e}"
    send_discord_message(message, api_key, secret_key, symbol)

# 在通道指標變動時發送盈虧信息
if channel_changed:
    message = (f"📢 **通道指標變動通知** 📢\n"
               f"📈 最新收盤價: ${close[last]:,.2f}\n"
               f"⬆️ 上軌: ${upperBand[last]:,.2f}\n"
               f"⬇️ 下軌: ${lowerBand[last]:,.2f}\n"
               f"➖ 中軌: ${middleBand[last]:,.2f}\n"
               f"🕒 更新時間: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    send_profit_loss_to_discord(api_key, secret_key, symbol, message)

@bot.command(name='1')
async def handle_command(ctx):
    # 计算上、中、下轨
    ohlcv = fetch_ohlcv(trading_pair)
    upperBand, lowerBand, middleBand, close = compute_channels(ohlcv, N)
    last = len(close) - 1
    # 生成图表并发送到Discord
    plot_channel_and_send_to_discord(
        ohlcv, upperBand, lowerBand, middleBand, last,
        f"📈 最新收盘价: ${close[last]:,.2f}\n"
        f"⬆️ 上轨: ${upperBand[last]:,.2f}\n"
        f"⬇️ 下轨: ${lowerBand[last]:,.2f}\n"
        f"➖ 中轨: ${middleBand[last]:,.2f}\n"
        f"🕒 时间: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        order_points=order_points
    )
    await ctx.send("图表已发送到Discord!")

@commands.command(name='2')
async def command_two(self, ctx):
    # 查询当前的营收信息并发送到Discord
    revenue_info = get_revenue_info()
    send_discord_message(f"💰 **当前营收信息**: {revenue_info}", self.api_key, self.secret_key)

class TradingBot(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.api_key = "b29c2647926baeafaccd04558dd78fc5"
        self.secret_key = "52ac11f07679ed99f5a068dbd7c54744"
        self.trading_pair = "ETH/USDT"
        self.symbol = TRADE_CONFIG[self.trading_pair]
        self.margin_coin = "USDT"
        self.leverage = 20
        self.wallet_percentage = 0.25
        self.N = 18
        self.order_points = []

    @commands.Cog.listener()
    async def on_ready(self):
        print(f'Logged in as {self.bot.user}')

bot = commands.Bot(command_prefix='/')
bot.add_cog(TradingBot(bot))

bot.run('YOUR_DISCORD_BOT_TOKEN')
