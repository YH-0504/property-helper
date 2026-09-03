import streamlit as st
import pdfplumber
import re
import pandas as pd

st.set_page_config(page_title="房產精耕謄本助手 Pro", layout="wide")

st.title("🏡 房產精耕小工具：建物電傳/謄本自動解析 (實務強化版)")
st.write("已加入**稱謂自動合併（去除星號）**與**地址隱匿/錯誤狀態偵測**，支援多檔批次匯出！")

uploaded_files = st.file_uploader("請拖曳或上傳建物謄本/電傳 PDF (可複選)", type=["pdf"], accept_multiple_files=True)

def parse_transcript_pdf(file):
    """ 解析華安電傳與官方地政謄本 """
    text = ""
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                text += t + "\n"

    # 清理表格符號與多餘空白
    lines = [re.sub(r"[\|\t]", " ", line).strip() for line in text.split("\n")]
    lines = [line for line in lines if line]
    full_clean = "\n".join(lines)

    data = {
        "檔名": getattr(file, "name", "未知"),
        "縣市行政區": "",
        "建物門牌": "未識別",
        "建號": "未識別",
        "建物總坪數": 0.0,
        "主建物(坪)": 0.0,
        "附屬陽台(坪)": 0.0,
        "公設坪數": 0.0,
        "所有權人": "未識別",
        "登記住址": "抓取錯誤",
        "登記原因": "未識別",
        "登記日期": "未識別",
        "建築完成日": "未識別",
        "主要用途": "未識別",
        "主要建材": "未識別"
    }

    # 1. 行政區段與建號
    sec_match = re.search(r"([^\n\r]+(?:市|縣)[^\n\r]+(?:區|鄉|鎮|市)[^\n\r]+(?:段|小段))\s*([0-9\-]+)\s*建號", full_clean)
    if sec_match:
        data["縣市行政區"] = sec_match.group(1).strip()
        data["建號"] = sec_match.group(2).strip()
    else:
        no_m = re.search(r"建\s*號[：:\s]*([0-9\-]+)", full_clean)
        if no_m:
            data["建號"] = no_m.group(1).strip()

    # 2. 標題下一行掃描（門牌、日期、用途、建材）
    for i, line in enumerate(lines):
        if "建物門牌" in line and i + 1 < len(lines):
            data["建物門牌"] = lines[i+1].replace("|", "").strip()
        if "建築完成日期" in line and i + 1 < len(lines):
            data["建築完成日"] = lines[i+1].replace("|", "").strip()
        if "主要用途" in line and i + 1 < len(lines):
            data["主要用途"] = lines[i+1].replace("|", "").strip()
        if "主要建材" in line and i + 1 < len(lines):
            data["主要建材"] = lines[i+1].replace("|", "").strip()

    # 3. 面積計算 (m² * 0.3025)
    main_m2 = 0.0
    main_match = re.search(r"層次面積\s*([\d\.]+)\s*平方公尺", full_clean)
    if main_match:
        main_m2 = float(main_match.group(1))
    data["主建物(坪)"] = round(main_m2 * 0.3025, 2)

    # 附屬建物
    sub_m2 = 0.0
    sub_matches = re.findall(r"(?:陽台|雨遮|平台|花台)[^\d\n\r]*?面積\s*([\d\.]+)\s*平方公尺", full_clean)
    if sub_matches:
        sub_m2 = sum([float(m) for m in sub_matches])
    data["附屬陽台(坪)"] = round(sub_m2 * 0.3025, 2)

    # 共有部分（公設坪數）
    pub_m2 = 0.0
    linear_text = full_clean.replace("\n", " ")
    pub_matches = re.findall(r"共有部分.*?建號\s*([\d\.]+)\s*平方公\s*尺.*?權利範圍\s*(\d+)\s*分之\s*(\d+)", linear_text)
    for p_area, denom, numer in pub_matches:
        try:
            pub_m2 += float(p_area) * (float(numer) / float(denom))
        except:
            pass
    data["公設坪數"] = round(pub_m2 * 0.3025, 2)
    data["建物總坪數"] = round(data["主建物(坪)"] + data["附屬陽台(坪)"] + data["公設坪數"], 2)

    # 4. 所有權部區塊定位
    owner_sec = full_clean
    if "建物所有權部" in full_clean:
        owner_sec = full_clean.split("建物所有權部")[1]
        if "建物他項權利部" in owner_sec:
            owner_sec = owner_sec.split("建物他項權利部")[0]

    # (A) 所有權人姓名（去除遮蔽星號）
    raw_owner = "未識別"
    owner_m = re.search(r"所有權人\s*\n\s*([^\n\r]+)", owner_sec)
    if owner_m:
        raw_owner = owner_m.group(1).replace("*", "").strip()

    # (B) 統一編號 / 身分證字號性別判斷
    title_suffix = ""
    id_m = re.search(r"(?:統一\s*編號|統編|身分證字號)[：:\s]*([A-Za-z])(\d)[0-9\*]+", owner_sec)
    if id_m:
        first_digit = id_m.group(2)
        if first_digit == "1":
            title_suffix = "先生"
        elif first_digit == "2":
            title_suffix = "女士"
    
    if raw_owner != "未識別":
        data["所有權人"] = raw_owner + title_suffix
    else:
        data["所有權人"] = "未識別"

    # (C) 戶籍/登記地址判斷（偵測是否隱匿或抓取錯誤）
    addr_m = re.search(r"(?:地址|住址)\s*([^\n\r]+)", owner_sec)
    if addr_m:
        extracted_addr = addr_m.group(1).strip()
        if "***" in extracted_addr or "隱匿" in extracted_addr:
            data["登記住址"] = "隱匿"
        elif len(extracted_addr) > 0:
            data["登記住址"] = extracted_addr
        else:
            data["登記住址"] = "抓取錯誤"
    else:
        data["登記住址"] = "抓取錯誤"

    # (D) 登記原因與日期
    reason_m = re.search(r"登記原因\s*([^\n\r]+)", owner_sec)
    if reason_m:
        data["登記原因"] = reason_m.group(1).strip()

    date_m = re.search(r"登記日期\s*(民國\s*\d+\s*年\s*\d+\s*月\s*\d+\s*日)", owner_sec)
    if date_m:
        data["登記日期"] = date_m.group(1).strip()

    return data, full_clean

# 介面處理與匯出
if uploaded_files:
    results = []
    raw_texts = {}

    with st.spinner(f"正在解析 {len(uploaded_files)} 份檔案..."):
        for file in uploaded_files:
            try:
                info, raw_t = parse_transcript_pdf(file)
                results.append(info)
                raw_texts[info["檔名"]] = raw_t
            except Exception as e:
                st.error(f"檔案 {file.name} 解析失敗：{e}")

    if results:
        st.success(f"✅ 成功解析 {len(results)} 筆物件！")
        df = pd.DataFrame(results)

        col_order = [
            "縣市行政區", "建物門牌", "建物總坪數", "主建物(坪)", "附屬陽台(坪)", "公設坪數",
            "所有權人", "登記住址", "登記原因", "登記日期", "建築完成日", "主要用途", "主要建材", "建號", "檔名"
        ]
        df = df[[c for c in col_order if c in df.columns]]

        st.subheader("📊 整理結果總表")
        st.dataframe(df, use_container_width=True)

        csv = df.to_csv(index=False).encode('utf-8-sig')
        st.download_button(
            label="📥 下載精耕名冊 (Excel CSV)",
            data=csv,
            file_name="社區精耕謄本整理名冊.csv",
            mime="text/csv",
        )

        with st.expander("🔍 查看 PDF 原始擷取文字（除錯對照用）"):
            sel_file = st.selectbox("選擇檔案：", list(raw_texts.keys()))
            st.text(raw_texts[sel_file])
