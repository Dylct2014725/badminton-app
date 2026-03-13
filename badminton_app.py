import streamlit as st
import pandas as pd
from datetime import datetime
import os
import plotly.graph_objects as go
import base64
from streamlit_calendar import calendar
import re
import time
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# --- 1. 基礎設定 ---
st.set_page_config(page_title="羽球管家 Pro", page_icon="🏸", layout="wide")

# --- Google Sheets 初始化連線 (修復格式報錯) ---
def init_gsheets():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    
    # 優先從 Streamlit Secrets 讀取 (雲端環境)
    if "gcp_service_account" in st.secrets:
        # 使用 dict() 複製品，避免直接改動 st.secrets 可能導致的唯讀報錯
        creds_dict = dict(st.secrets["gcp_service_account"])
        
        # --- 核心修復：清理 Private Key ---
        raw_key = creds_dict["private_key"]
        
        # 1. 處理轉義的 \n
        clean_key = raw_key.replace("\\n", "\n")
        # 2. 徹底移除頭尾空白、換行、以及可能誤入的引號 (解決 65 字元報錯)
        clean_key = clean_key.strip().strip('"').strip("'").strip()
        
        creds_dict["private_key"] = clean_key
        
        try:
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        except Exception as e:
            st.error(f"認證字典轉換失敗: {e}")
            raise e
            
    # 如果沒有 Secrets，則找本地檔案 (電腦環境)
    elif os.path.exists("key.json"):
        creds = ServiceAccountCredentials.from_json_keyfile_name("key.json", scope)
    else:
        raise FileNotFoundError("找不到任何 Google Sheets 認證資訊（Secrets 或 key.json）")
        
    client = gspread.authorize(creds)
    return client.open("Badminton_Data")

# 讀取錢幣圖示
def get_base64_of_bin_file(bin_file):
    if os.path.exists(bin_file):
        with open(bin_file, 'rb') as f:
            data = f.read()
        return base64.b64encode(data).decode()
    return None

encoded_image = get_base64_of_bin_file('money_icon.png')

# --- 2. 自定義 CSS ---
st.markdown("""
    <style>
    .main { background-color: #FFFFFF; }
    .record-card {
        background-color: white; border: 1px solid #E0E0E0; border-radius: 16px; 
        margin-bottom: 20px; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.05);
    }
    .card-header {
        display: flex; justify-content: space-between; align-items: center; 
        padding: 15px 20px; background-color: #f8f9fa; border-bottom: 1.5px solid #eee;
    }
    .item-row {
        display: flex; align-items: center; padding: 12px 20px; border-bottom: 1px solid #F5F5F5;
    }
    .icon-circle {
        width: 38px; height: 38px; border-radius: 50%; display: flex; 
        align-items: center; justify-content: center; margin-right: 15px; color: white; font-size: 18px;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 3. 數據處理函數 ---
def load_data():
    if 'records' not in st.session_state or 'members' not in st.session_state:
        try:
            sh = init_gsheets()
            
            # 1. 處理 records
            try:
                wks_rec = sh.worksheet("records")
            except:
                wks_rec = sh.add_worksheet(title="records", rows="1000", cols="20")
                headers = ["日期", "時間", "地點", "人數", "場租", "用球", "單球單價", "總收入", "總支出", "損益", "名單"]
                wks_rec.update('A1', [headers])
            
            data_rec = wks_rec.get_all_records()
            if data_rec:
                df_rec = pd.DataFrame(data_rec)
                # 強制轉換數字，避免繪圖報錯
                numeric_cols = ['場租', '用球', '單球單價', '總收入', '總支出', '損益', '人數']
                for col in numeric_cols:
                    if col in df_rec.columns:
                        df_rec[col] = pd.to_numeric(df_rec[col], errors='coerce').fillna(0)
                
                df_rec['日期'] = pd.to_datetime(df_rec['日期']).dt.normalize()
                st.session_state.records = df_rec.to_dict('records')
            else:
                st.session_state.records = []

            # 2. 處理 members
            try:
                wks_mem = sh.worksheet("members")
            except:
                wks_mem = sh.add_worksheet(title="members", rows="500", cols="5")
                wks_mem.update('A1', [["姓名", "電話", "備註"]])
            
            data_mem = wks_mem.get_all_records()
            st.session_state.members = pd.DataFrame(data_mem) if data_mem else pd.DataFrame(columns=["姓名", "電話", "備註"])

        except Exception as e:
            st.warning(f"⚠️ 雲端連線失敗，目前為本地模式。({str(e)})")
            # 本地備援讀取
            if os.path.exists('badminton_records.csv'):
                df = pd.read_csv('badminton_records.csv')
                df['日期'] = pd.to_datetime(df['日期'], errors='coerce').dt.normalize()
                st.session_state.records = df.dropna(subset=['日期']).to_dict('records')
            else:
                st.session_state.records = []
            
            if os.path.exists('members_db.csv'):
                st.session_state.members = pd.read_csv('members_db.csv', encoding='utf-8-sig')
            else:
                st.session_state.members = pd.DataFrame(columns=["姓名", "電話", "備註"])

def save_data():
    """同步存儲到雲端與本地"""
    if 'records' in st.session_state and st.session_state.records:
        df_rec = pd.DataFrame(st.session_state.records)
        df_rec['日期'] = pd.to_datetime(df_rec['日期']).dt.strftime('%Y-%m-%d')
        df_rec.to_csv("badminton_records.csv", index=False, encoding='utf-8-sig')
        try:
            sh = init_gsheets()
            wks = sh.worksheet("records")
            wks.clear()
            wks.update([df_rec.columns.values.tolist()] + df_rec.values.tolist())
        except: pass

    if 'members' in st.session_state:
        st.session_state.members.to_csv("members_db.csv", index=False, encoding='utf-8-sig')
        try:
            sh = init_gsheets()
            wks_m = sh.worksheet("members")
            wks_m.clear()
            wks_m.update([st.session_state.members.columns.values.tolist()] + st.session_state.members.values.tolist())
        except: pass

def save_to_gsheets(new_entry):
    try:
        sh = init_gsheets()
        wks = sh.worksheet("records")
        wks.append_row([
            new_entry['日期'], new_entry['時間'], new_entry['地點'],
            new_entry['人數'], new_entry['場租'], new_entry['用球'],
            new_entry.get('單球單價', 12), new_entry['總收入'],
            new_entry['總支出'], new_entry['損益'], new_entry['名單']
        ])
        return True
    except: return False

# 啟動時讀取
load_data()

# --- 4. 側邊欄 ---
st.sidebar.title("🏸 羽球管家")
page = st.sidebar.radio("功能導覽", ["📊 財務概覽", "📝 快速記帳", "👥 隊員管理", "📜 歷史數據"])

# --- 5. 頁面邏輯 ---
if page == "📊 財務概覽":
    st.markdown("# 📊 財務概覽")
    df = pd.DataFrame(st.session_state.records) if st.session_state.records else pd.DataFrame()
    
    if not df.empty:
        df['日期'] = pd.to_datetime(df['日期'])
        month_list = sorted(df['日期'].dt.strftime('%Y-%m').unique(), reverse=True)
        sel_month = st.selectbox("選擇月份", month_list)
        m_df = df[df['日期'].dt.strftime('%Y-%m') == sel_month].copy()
        
        t_exp = m_df['總支出'].sum()
        t_inc = m_df['總收入'].sum()
        balance = t_inc - t_exp

        c1, c2, c3 = st.columns([1, 2, 1])
        c1.metric("月支出", f"${t_exp:,.0f}")
        c3.metric("月收入", f"${t_inc:,.0f}")
        
        # 圓環圖
        fig = go.Figure(data=[go.Pie(
            labels=['支出', '收入'], values=[t_exp, t_inc], hole=0.7,
            marker=dict(colors=['#FFCC00', '#33CCFF']), textinfo='none'
        )])
        fig.add_annotation(text=f"結餘<br>${balance:,.0f}", showarrow=False, font_size=20)
        fig.update_layout(showlegend=False, height=300, margin=dict(t=0, b=0))
        c2.plotly_chart(fig, use_container_width=True)

        st.subheader("🗓️ 活動紀錄")
        for _, row in m_df.sort_values('日期', ascending=False).iterrows():
            st.markdown(f"""
            <div class="record-card">
                <div class="card-header">
                    <b>{row['日期'].strftime('%Y-%m-%d')}</b>
                    <b style="color:{'#28A745' if row['損益']>=0 else '#FF4B4B'}">${row['損益']:,.0f}</b>
                </div>
                <div class="item-row">📍 {row['地點']} | 👥 {row['人數']}人</div>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.info("尚無數據，請先前往快速記帳。")

elif page == "📝 快速記帳":
    st.markdown("# 📝 活動記帳")
    col_d, col_s, col_e = st.columns(3)
    d = col_d.date_input("日期", datetime.now())
    st_t = col_s.selectbox("開始", [f"{h:02d}:00" for h in range(24)], index=18)
    en_t = col_e.selectbox("結束", [f"{h:02d}:00" for h in range(24)], index=20)
    
    loc = st.text_input("地點", "林士德體育館")
    c1, c2 = st.columns(2)
    fee = c1.number_input("場租", value=120)
    balls = c1.number_input("用球數", value=6)
    price = c2.number_input("每人收費", value=50)
    
    st.divider()
    m_options = st.session_state.members["姓名"].tolist() if not st.session_state.members.empty else []
    sel_m = st.multiselect("選擇隊員", m_options)
    others = st.text_area("其他臨時人員 (逗號分隔)")
    
    all_p = list(set(sel_m + [p.strip() for p in re.split(r'[,，\s]+', others) if p.strip()]))
    
    if st.button("🚀 儲存紀錄", use_container_width=True) and all_p:
        total_exp = fee + (balls * 12)
        total_inc = len(all_p) * price
        new_entry = {
            "日期": d.strftime('%Y-%m-%d'), "時間": f"{st_t}-{en_t}", "地點": loc,
            "人數": len(all_p), "場租": fee, "用球": balls, "單球單價": 12,
            "總收入": total_inc, "總支出": total_exp, "損益": total_inc - total_exp,
            "名單": ", ".join(all_p)
        }
        if save_to_gsheets(new_entry):
            st.session_state.records.append(new_entry)
            save_data()
            st.success("存檔成功！")
            time.sleep(1)
            st.rerun()

elif page == "👥 隊員管理":
    st.markdown("# 👥 隊員管理")
    with st.form("add_m"):
        name = st.text_input("姓名")
        phone = st.text_input("電話")
        if st.form_submit_button("新增") and name:
            new_df = pd.DataFrame([{"姓名": name, "電話": phone, "備註": "常客"}])
            st.session_state.members = pd.concat([st.session_state.members, new_df], ignore_index=True)
            save_data()
            st.rerun()
    st.dataframe(st.session_state.members, use_container_width=True, hide_index=True)

elif page == "📜 歷史數據":
    st.markdown("# 📜 歷史紀錄")
    if st.session_state.records:
        df_h = pd.DataFrame(st.session_state.records)
        st.dataframe(df_h, use_container_width=True)
        if st.button("清空本地快取 (不影響雲端)"):
            st.session_state.clear()
            st.rerun()
