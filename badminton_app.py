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

# --- Google Sheets 初始化連線 ---
def init_gsheets():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    # 確保 key.json 檔案跟 .py 檔在同一個資料夾
    creds = ServiceAccountCredentials.from_json_keyfile_name("key.json", scope)
    client = gspread.authorize(creds)
    # 打開你在 Google Drive 建立的試算表名稱
    return client.open("Badminton_Data")

def get_base64_of_bin_file(bin_file):
    if os.path.exists(bin_file):
        with open(bin_file, 'rb') as f:
            data = f.read()
        return base64.b64encode(data).decode()
    return None

# 讀取錢幣圖示
encoded_image = get_base64_of_bin_file('money_icon.png')

# --- 2. 自定義 CSS ---
st.markdown("""
    <style>
    .main { background-color: #FFFFFF; }
    .record-card {
        background-color: white; 
        border: 1px solid #E0E0E0; 
        border-radius: 16px; 
        margin-bottom: 20px;
        overflow: hidden; 
        box-shadow: 0 4px 12px rgba(0,0,0,0.05);
    }
    .card-header {
        display: flex; 
        justify-content: space-between; 
        align-items: center; 
        padding: 15px 20px; 
        background-color: #f8f9fa;
        border-bottom: 1.5px solid #eee;
    }
    .item-row {
        display: flex; 
        align-items: center; 
        padding: 12px 20px; 
        border-bottom: 1px solid #F5F5F5;
    }
    .icon-circle {
        width: 38px; height: 38px; 
        border-radius: 50%; 
        display: flex; 
        align-items: center; 
        justify-content: center; 
        margin-right: 15px; 
        color: white; 
        font-size: 18px;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 3. 數據處理函數 (整合雲端與本地) ---
def load_data():
    # 只要 session_state 還沒初始化，就執行載入邏輯
    if 'records' not in st.session_state or 'members' not in st.session_state:
        try:
            sh = init_gsheets()
            
            # 1. 處理「打球紀錄」 (records)
            try:
                wks_rec = sh.worksheet("records")
            except:
                # 若分頁不存在則新建，並寫入標題
                wks_rec = sh.add_worksheet(title="records", rows="1000", cols="20")
                headers = ["日期", "時間", "地點", "人數", "場租", "用球", "單球單價", "總收入", "總支出", "損益", "名單"]
                wks_rec.update('A1', [headers])
            
            data_rec = wks_rec.get_all_records()
            if data_rec:
                df_rec = pd.DataFrame(data_rec)
                # 轉換日期格式
                df_rec['日期'] = pd.to_datetime(df_rec['日期']).dt.normalize()
                st.session_state.records = df_rec.to_dict('records')
            else:
                st.session_state.records = []

            # 2. 處理「隊員名單」 (members)
            try:
                wks_mem = sh.worksheet("members")
            except:
                wks_mem = sh.add_worksheet(title="members", rows="500", cols="5")
                mem_headers = ["姓名", "電話", "備註"]
                wks_mem.update('A1', [mem_headers])
            
            data_mem = wks_mem.get_all_records()
            if data_mem:
                st.session_state.members = pd.DataFrame(data_mem)
            else:
                st.session_state.members = pd.DataFrame(columns=["姓名", "電話", "備註"])

        except Exception as e:
            # 使用 str(e) 確保看到的是文字訊息而非 <Response [200]>
            error_msg = str(e)
            st.warning(f"⚠️ 雲端同步失敗，已切換至本地模式。原因：{error_msg}")
            
            # --- 本地備援邏輯 ---
            # 讀取紀錄
            if os.path.exists('badminton_records.csv'):
                df = pd.read_csv('badminton_records.csv')
                df['日期'] = pd.to_datetime(df['日期'], errors='coerce').dt.normalize()
                df = df.dropna(subset=['日期'])
                if '單球單價' not in df.columns: df['單球單價'] = 12
                st.session_state.records = df.to_dict('records')
            else:
                st.session_state.records = []

            # 讀取名單
            if os.path.exists('members_db.csv'):
                st.session_state.members = pd.read_csv('members_db.csv', encoding='utf-8-sig')
            else:
                st.session_state.members = pd.DataFrame(columns=["姓名", "電話", "備註"])
def save_data():
    """確保數據同步儲存至雲端與本地"""
    if 'records' in st.session_state and st.session_state.records:
        df_rec = pd.DataFrame(st.session_state.records)
        df_rec['日期'] = pd.to_datetime(df_rec['日期']).dt.strftime('%Y-%m-%d')
        
        # 存至本地
        df_rec.to_csv("badminton_records.csv", index=False, encoding='utf-8-sig')
        
        # 存至雲端 (全量覆蓋以確保一致性，或可根據需求改為 append)
        try:
            sh = init_gsheets()
            wks = sh.worksheet("records")
            wks.clear()
            wks.update([df_rec.columns.values.tolist()] + df_rec.values.tolist())
        except Exception as e:
            st.error(f"雲端儲存失敗：{e}")

    if 'members' in st.session_state:
        st.session_state.members.to_csv("members_db.csv", index=False, encoding='utf-8-sig')
        try:
            sh = init_gsheets()
            wks_mem = sh.worksheet("members")
            wks_mem.clear()
            wks_mem.update([st.session_state.members.columns.values.tolist()] + st.session_state.members.values.tolist())
        except:
            pass

def save_to_gsheets(new_entry):
    """單筆新增至雲端"""
    try:
        sh = init_gsheets()
        wks = sh.worksheet("records")
        row = [
            new_entry['日期'], new_entry['時間'], new_entry['地點'],
            new_entry['人數'], new_entry['場租'], new_entry['用球'],
            new_entry.get('單球單價', 12), new_entry['總收入'],
            new_entry['總支出'], new_entry['損益'], new_entry['名單']
        ]
        wks.append_row(row)
        return True
    except Exception as e:
        st.error(f"儲存到雲端失敗：{e}")
        return False

# 啟動時立即加載
load_data()

# --- 4. 側邊欄導航 ---
st.sidebar.title("🏸 羽球管家")
page = st.sidebar.radio("功能導覽", ["📊 財務概覽", "📝 快速記帳", "👥 隊員管理", "📜 歷史數據"])

# --- 5. 頁面邏輯 ---
if page == "📊 財務概覽":
    df = pd.DataFrame(st.session_state.records) if st.session_state.records else pd.DataFrame(columns=['日期', '總支出', '總收入', '損益', '地點', '人數', '場租', '用球', '單球單價'])
    
    col_title, col_mode = st.columns([2, 1])
    with col_title:
        st.markdown("# 📊 財務概覽")
    with col_mode:
        v_mode = st.radio("模式切換", ["月", "日"], horizontal=True)

    if v_mode == "月":
        if not df.empty:
            df['日期'] = pd.to_datetime(df['日期'])
            month_list = sorted(df['日期'].dt.strftime('%Y-%m').unique(), reverse=True)
            sel_month = st.selectbox("選擇月份", month_list)
            m_df = df[df['日期'].dt.strftime('%Y-%m') == sel_month]
        else:
            m_df = pd.DataFrame()

        t_exp = m_df['總支出'].sum() if not m_df.empty else 0
        t_inc = m_df['總收入'].sum() if not m_df.empty else 0
        balance = t_inc - t_exp

        c_left, c_chart, c_right = st.columns([1, 2, 1])
        with c_left:
            st.markdown(f"<div><span style='background:#FFCC00;padding:4px 12px;border-radius:12px;font-weight:bold;'>月支出</span><br><h1>${t_exp:,.0f}</h1></div>", unsafe_allow_html=True)
        
        with c_chart:
            fig = go.Figure(data=[go.Pie(
                labels=['支出', '收入'],
                values=[t_exp, t_inc] if (t_exp+t_inc)>0 else [1, 0.001],
                hole=0.75,
                marker=dict(colors=['#FFCC00', '#33CCFF'], line=dict(color='white', width=5)),
                textinfo='none', hoverinfo='skip', sort=False
            )])
            
            if encoded_image:
                fig.add_layout_image(
                    dict(source=f"data:image/png;base64,{encoded_image}",
                        xref="paper", yref="paper", x=0.5, y=0.6, sizex=0.35, sizey=0.35, xanchor="center", yanchor="middle")
                )

            fig.add_annotation(
                    text=f"<span style='font-size:18px; color:#888;'>月結餘</span><br><br><br><b style='font-size:38px; color:#333;'>${balance:,.0f}</b>",
                    showarrow=False, x=0.5, y=0.25, align="center"
                )
            
            fig.update_layout(showlegend=False, margin=dict(t=0, b=0, l=0, r=0), height=350, paper_bgcolor='rgba(0,0,0,0)')
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
            
        with c_right:
            st.markdown(f"<div style='text-align: right;'><span style='background:#33CCFF;color:white;padding:4px 12px;border-radius:12px;font-weight:bold;'>月收入</span><br><h1>${t_inc:,.0f}</h1></div>", unsafe_allow_html=True)

        if not m_df.empty:
            st.subheader("🗓️ 本月活動紀錄")
            w_map = {0:'星期一', 1:'星期二', 2:'星期三', 3:'星期四', 4:'星期五', 5:'星期六', 6:'星期日'}
            for _, row in m_df.sort_values('日期', ascending=False).iterrows():
                dt = row['日期']
                p_color = "#FF4B4B" if row['損益'] < 0 else "#28A745"
                p_sign = "+" if row['損益'] > 0 else "-" if row['損益'] < 0 else ""
                
                st.markdown(f"""
                <div class="record-card">
                    <div class="card-header">
                        <span style="font-weight: bold;">{dt.strftime('%Y/%m/%d')} {w_map[dt.weekday()]}</span>
                        <span style="font-weight: bold; color: {p_color};">{p_sign}${abs(row['損益']):,.0f}</span>
                    </div>
                    <div class="card-body">
                        <div class="item-row">
                            <div class="icon-circle" style="background-color: #FF3366;">🏸</div>
                            <div style="flex-grow: 1;"><b>場租支出</b> ({row['地點']})</div>
                            <div><b>$-{row['場租']:,.0f}</b></div>
                        </div>  
                        <div class="item-row">
                            <div class="icon-circle" style="background-color: #FF9F00;">🎾</div>
                            <div style="flex-grow: 1;"><b>羽毛球耗材</b></div>
                            <div><b>$-{row['用球'] * row['單球單價']:,.0f}</b></div>
                        </div>
                        <div class="item-row" style="border-bottom: none;">
                            <div class="icon-circle" style="background-color: #28A745;">👥</div>
                            <div style="flex-grow: 1;"><b>活動收入</b> ({row['人數']} 人)</div>
                            <div><b>$+{row['總收入']:,.0f}</b></div>
                        </div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
    else:
        df['日期'] = pd.to_datetime(df['日期'])
        calendar_events = []
        if not df.empty:
            for _, row in df.iterrows():
                if pd.notna(row['日期']):
                    calendar_events.append({
                        "title": f"${row['損益']:,.0f}",
                        "start": row['日期'].strftime('%Y-%m-%d'),
                        "backgroundColor": "#28A745" if row['損益'] >= 0 else "#FF4B4B"
                    })

        if 'selected_date' not in st.session_state:
            st.session_state.selected_date = None

        cal_options = {
            "initialView": "dayGridMonth",
            "height": 600,
            "selectable": True,
            "headerToolbar": {"left": "prev,next today", "center": "title", "right": "dayGridMonth"}
        }

        state = calendar(events=calendar_events, options=cal_options, key='badminton_calendar_day')

        if state and isinstance(state, dict) and 'dateClick' in state:
            clicked_date = state['dateClick'].get('date', '').split('T')[0]
            st.session_state.selected_date = clicked_date
            st.rerun()

        if st.session_state.selected_date:
            selected_str = st.session_state.selected_date
            st.markdown(f"### 📅 {selected_str} 活動明細")
            display_df = df[df['日期'].dt.strftime('%Y-%m-%d') == selected_str]

            if display_df.empty:
                st.info("💡 該日期沒有活動紀錄")
            else:
                w_map = {0:'星期一', 1:'星期二', 2:'星期三', 3:'星期四', 4:'星期五', 5:'星期六', 6:'星期日'}
                for _, row in display_df.iterrows():
                    dt = row['日期']
                    p_color = "#FF4B4B" if row['損益'] < 0 else "#28A745"
                    p_sign = "+" if row['損益'] > 0 else "-" if row['損益'] < 0 else ""
                    st.markdown(f"""
                    <div class="record-card">
                        <div class="card-header">
                            <span style="font-weight: bold;">{dt.strftime('%Y/%m/%d')} {w_map[dt.weekday()]}</span>
                            <span style="font-weight: bold; color: {p_color};">{p_sign}${abs(row['損益']):,.0f}</span>
                        </div>
                        <div class="card-body">
                            <div class="item-row">
                                <div class="icon-circle" style="background-color: #FF3366;">🏸</div>
                                <div style="flex-grow: 1;"><b>場租支出</b> ({row['地點']})</div>
                                <div><b>$-{row['場租']:,.0f}</b></div>
                            </div>
                            <div class="item-row">
                                <div class="icon-circle" style="background-color: #FF9F00;">🎾</div>
                                <div style="flex-grow: 1;"><b>羽毛球耗材</b></div>
                                <div><b>$-{row['用球'] * row['單球單價']:,.0f}</b></div>
                            </div>
                            <div class="item-row" style="border-bottom: none;">
                                <div class="icon-circle" style="background-color: #28A745;">👥</div>
                                <div style="flex-grow: 1;"><b>活動收入</b> ({row['人數']} 人)</div>
                                <div><b>$+{row['總收入']:,.0f}</b></div>
                            </div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

elif page == "📝 快速記帳":
    st.markdown("# 📝 活動記帳")
    time_options = [f"{h:02d}:{m:02d}" for h in range(24) for m in (0, 30)]

    col_d, col_s, col_e = st.columns(3)
    with col_d:
        date_val = st.date_input("活動日期", datetime.now())
    with col_s:
        start_time = st.selectbox("開始時間", options=time_options, index=38)
    with col_e:
        end_time = st.selectbox("結束時間", options=time_options, index=42)
    
    location = st.text_input("地點", "林士德體育館")
    
    col1, col2 = st.columns(2)
    with col1:
        court_fee = st.number_input("場租金額", value=120, min_value=0)
        shuttle_count = st.number_input("消耗球數", value=6, min_value=0)
        ball_price = st.number_input("單球單價", value=12, min_value=0)
    with col2:
        fee = st.number_input("每人收費 (HKD)", value=50, min_value=0)
        expected_players = st.number_input("預計參加人數", value=6, min_value=1)

    st.divider()
    st.subheader("🙋 參加者名單")

    member_options = st.session_state.members["姓名"].tolist() 
    selected_members = st.multiselect("從常客清單挑選：", options=member_options)
    manual_players = st.text_area("手動輸入臨時成員 (逗號或換行分隔)")
    
    temp_list = [str(p).strip() for p in re.split(r'[,，\n\s]+', manual_players) if p.strip()] if manual_players else []
    all_players = list(set([str(m) for m in selected_members] + temp_list))
    num_players = len(all_players)

    can_save = True 
    if num_players > expected_players:
        st.error(f"❌ 錯誤：實際人數 ({num_players}) 已超過預計人數 ({expected_players})！")
        can_save = False 
    elif num_players == 0:
        st.info("💡 請選擇或輸入參加者。")
        can_save = False
    else:
        st.success(f"✅ 人數確認：共 {num_players} 人。")

    if all_players:
        st.write(f"當前名單：`{', '.join(all_players)}`")
    
    if st.button("🚀 儲存活動紀錄", use_container_width=True, disabled=not can_save):
        total_expense = court_fee + (shuttle_count * ball_price)
        total_income = num_players * fee
        net_profit = total_income - total_expense
        
        new_entry = {
            "日期": date_val.strftime('%Y-%m-%d'),
            "時間": f"{start_time}-{end_time}",
            "地點": location,
            "人數": num_players,
            "場租": court_fee,
            "用球": shuttle_count,
            "單球單價": ball_price,
            "總收入": total_income,
            "總支出": total_expense,
            "損益": net_profit,
            "名單": ", ".join(all_players)
        }
        
        with st.spinner('正在同步至雲端...'):
            if save_to_gsheets(new_entry):
                st.session_state.records.append(new_entry)
                save_data() # 本地備份
                st.balloons()
                st.success("✅ 雲端同步成功！")
                time.sleep(1)
                st.rerun()

elif page == "👥 隊員管理":
    st.markdown("# 👥 隊員資料庫")
    col1, col2 = st.columns([1, 1.5])
    
    with col1:
        with st.expander("➕ 新增成員", expanded=True):
            new_name = st.text_input("姓名", key="add_n")
            new_phone = st.text_input("電話", key="add_p")
            if st.button("確認新增", use_container_width=True) and new_name:
                new_m = pd.DataFrame([{"姓名": new_name, "電話": new_phone, "備註": "常客"}])
                st.session_state.members = pd.concat([st.session_state.members, new_m], ignore_index=True)
                save_data()
                st.success(f"✅ 已加入：{new_name}")
                st.rerun()
        
        if not st.session_state.members.empty:
            st.write("---")
            st.subheader("✏️ 修改/刪除")
            m_list = st.session_state.members["姓名"].tolist()
            edit_target = st.selectbox("選擇隊員：", options=m_list)
            m_idx = st.session_state.members[st.session_state.members["姓名"] == edit_target].index[0]
            
            with st.form("edit_form"):
                upd_phone = st.text_input("修改電話", value=str(st.session_state.members.at[m_idx, "電話"]))
                upd_note = st.text_input("修改備註", value=str(st.session_state.members.at[m_idx, "備註"]))
                if st.form_submit_button("💾 儲存修改", use_container_width=True):
                    st.session_state.members.at[m_idx, "電話"] = upd_phone
                    st.session_state.members.at[m_idx, "備註"] = upd_note
                    save_data()
                    st.success("更新成功！")
                    st.rerun()
            
            if st.button("🗑️ 刪除此成員", use_container_width=True, type="secondary"):
                st.session_state.members = st.session_state.members.drop(m_idx)
                save_data()
                st.rerun()

    with col2:
        st.subheader("📋 現有清單")
        st.dataframe(st.session_state.members, use_container_width=True, hide_index=True)

elif page == "📜 歷史數據":
    st.markdown("# 📜 歷史數據報表")
    if st.session_state.records:
        history_df = pd.DataFrame(st.session_state.records)

        if '日期' in history_df.columns:
            history_df['日期'] = pd.to_datetime(history_df['日期']).dt.date
            
        st.dataframe(history_df, use_container_width=True, hide_index=True)
        
        st.write("---")
        record_options = [f"#{i} | {r['日期']} - {r['地點']}" for i, r in enumerate(st.session_state.records)]
        
        col_edit, col_del = st.columns(2)
        
        with col_edit:
            st.subheader("✏️ 修改紀錄")
            to_edit = st.selectbox("選擇要修改的紀錄：", options=record_options, key="edit_select")
            edit_idx = int(to_edit.split("|")[0].replace("#", "").strip())
            
            with st.expander("展開編輯內容"):
                current_rec = st.session_state.records[edit_idx]
                new_date = st.date_input("修改日期", pd.to_datetime(current_rec['日期']))
                new_loc = st.text_input("修改地點", current_rec['地點'])
                
                c1, c2 = st.columns(2)
                with c1:
                    new_court = st.number_input("場租", value=int(current_rec['場租']))
                    new_shuttle = st.number_input("球數", value=int(current_rec['用球']))
                with c2:
                    new_players = st.number_input("人數", value=int(current_rec['人數']))
                    new_price = st.number_input("單球單價", value=int(current_rec.get('單球單價', 12)))
                
                new_income = st.number_input("總收入", value=int(current_rec['總收入']))
                
                if st.button("💾 儲存修改", use_container_width=True):
                    new_exp = new_court + (new_shuttle * new_price)
                    st.session_state.records[edit_idx].update({
                        "日期": new_date.strftime("%Y-%m-%d"),
                        "地點": new_loc,
                        "人數": new_players,
                        "場租": new_court,
                        "用球": new_shuttle,
                        "單球單價": new_price,
                        "總收入": new_income,
                        "總支出": new_exp,
                        "損益": new_income - new_exp
                    })
                    save_data()
                    st.success("✅ 紀錄更新成功！")
                    st.rerun()

        with col_del:
            st.subheader("🗑️ 刪除紀錄")
            to_delete = st.selectbox("選擇要刪除的紀錄：", options=record_options, key="del_select")
            if st.button("❌ 確定永久刪除", use_container_width=True):
                del_idx = int(to_delete.split("|")[0].replace("#", "").strip())
                st.session_state.records.pop(del_idx)
                save_data()
                st.rerun()
            
        csv = history_df.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 下載完整數據 CSV", data=csv, file_name="badminton_records.csv", mime="text/csv")
    else:
        st.info("暫無紀錄")