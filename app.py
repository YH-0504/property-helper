import streamlit as st
import pdfplumber
import re
import pandas as pd

st.set_page_config(page_title="房產精耕謄本助手", layout="wide")

st.title("🏡 房產精耕小工具：謄本精準擷取")
st.write("已聚焦精耕 5 大關鍵資訊：完整門牌、坪數拆解、車位編號、姓名+性別、戶籍地址。")

uploaded_files = st.file_uploader("請拖曳或上傳建物謄本/電傳 PDF (可複選多個)", type=["pdf"], accept_multiple_files=True)

def parse_transcript_pdf(file):
    pages_text = []
    with pdfplumber.open(file) as pdf:
        for p in pdf.pages:
            t = p.extract_text()
            pages_text.append(t if t else "")

    full_text = "\n".join(pages_text)
    clean_full = re.sub(r"[\|\t]", " ", full_text)
    lines = [line.strip() for line in clean_full.split("\n") if line.strip()]

    data = {
        "建物門牌": "未識別",
        "總坪數": 0.0,
        "主建物(坪)": 0.0,
        "附屬(坪)": 0.0,
        "公設(坪)": 0.0,
        "車位標示": "無/未標示",
        "所有權人": "未識別",
        "戶籍地址": "抓取錯誤"
    }

    # -------------------------------------------------------------
    # 1. 建物完整門牌 (自動結合「縣市行政區」+「門牌號碼」)
    # -------------------------------------------------------------
    city_district = ""
    # 從頂部抓取「臺南市東區」等行政區
    admin_match = re.search(r"([^\n\r\s]+(?:市|縣)[^\n\r\s]+(?:區|鄉|鎮|市))", clean_full)
    if admin_match:
        city_district = admin_match.group(1).strip()

    raw_doorplate = ""
    for i, line in enumerate(lines):
        if "建物門牌" in line and i + 1 < len(lines):
            raw_doorplate = lines[i+1].replace("|", "").strip()
            break

    if raw_doorplate:
        # 若門牌本身未含縣市，自動在前面補上行政區
        if any(c in raw_doorplate for c in ["市", "縣"]):
            data["建物門牌"] = raw_doorplate
        else:
            data["建物門牌"] = f"{city_district}{raw_doorplate}"

    # -------------------------------------------------------------
    # 2. 面積計算 (主建物、附屬、公設、總坪數)
    # -------------------------------------------------------------
    # 主建物 (層次面積)
    main_m2 = 0.0
    main_match = re.search(r"層次面積\s*([\d\.]+)\s*平方公尺", clean_full)
    if main_match:
        main_m2 = float(main_match.group(1))
    data["主建物(坪)"] = round(main_m2 * 0.3025, 2)

    # 附屬建物 (陽台、雨遮等)
    sub_m2 = 0.0
    sub_matches = re.findall(r"(?:陽台|雨遮|平台|花台)[^\d\n\r]*?面積\s*([\d\.]+)\s*平方公尺", clean_full)
    if sub_matches:
        sub_m2 = sum([float(m) for m in sub_matches])
    data["附屬(坪)"] = round(sub_m2 * 0.3025, 2)

    # 共有公設 (計算持分面積)
    pub_m2 = 0.0
    linear_text = clean_full.replace("\n", " ")
    pub_matches = re.findall(r"共有部分.*?建號\s*([\d\.]+)\s*平方公\s*尺.*?權利範圍\s*(\d+)\s*分之\s*(\d+)", linear_text)
    for p_area, denom, numer in pub_matches:
        try:
            pub_m2 += float(p_area) * (float(numer) / float(denom))
        except:
            pass
    data["公設(坪)"] = round(pub_m2 * 0.3025, 2)

    # 總坪數加總
    data["總坪數"] = round(data["主建物(坪)"] + data["附屬(坪)"] + data["公設(坪)"], 2)

    # -------------------------------------------------------------
    # 3. 車位標示 (抓取公設其他標示或備註中的車位編號，如 B4-105、地下一層車位編號等)
    # -------------------------------------------------------------
    parking_match = re.search(r"(?:編號|車位)[：:\s]*([A-Za-z0-9\-\_]+号|[A-Za-z0-9\-\_]+號|[B|b]\d+[\s\-]*(?:號)?\d*)", clean_full)
    if not parking_match:
        # 備用匹配：含地下室或停車位字樣
        parking_match = re.search(r"(地下一層|地下二層|地下三層|地下四層|地下五層|B[1-5])[^\n\r]*?(?:車位|編號)[：:\s]*([^\n\r\s]+)", clean_full)
        if parking_match:
            data["車位標示"] = f"{parking_match.group(1)} {parking_match.group(2)}"
    else:
        data["車位標示"] = parking_match.group(1).strip()

    # -------------------------------------------------------------
    # 4 & 5. 所有權人 (姓名+性別) 與 戶籍地址 (通常在第2頁建物所有權部)
    # -------------------------------------------------------------
    # 優先定位建物所有權部區塊
    owner_sec = clean_full
    if "建物所有權部" in clean_full:
        owner_sec = clean_full.split("建物所有權部")[1]
        if "建物他項權利部" in owner_sec:
            owner_sec = owner_sec.split("建物他項權利部")[0]
    elif len(pages_text) >= 2:
        # 若無關鍵字但有多頁，讀取第二頁以後內容
        owner_sec = "\n".join(pages_text[1:])

    # 4. 所有權人姓名 + 稱謂
    raw_name = ""
    name_match = re.search(r"所有權人\s*\n\s*([^\n\r]+)", owner_sec)
    if name_match:
        # 移除星號
        raw_name = name_match.group(1).replace("*", "").strip()

    title = ""
    # 身分證第一碼數字判斷：1先生、2女士
    id_match = re.search(r"([A-Za-z])\s*([12])\s*[\d\*]{2,}", owner_sec)
    if id_match:
        code = id_match.group(2)
        if code == "1":
            title = "先生"
        elif code == "2":
            title = "女士"

    if raw_name:
        data["所有權人"] = raw_name + title
    else:
        data["所有權人"] = "未識別"

    # 5. 戶籍地址 (排除「權利範圍」字眼與判斷是否隱匿)
    addr_match = re.search(r"(?:地址|住址)\s*[:：\s]*([^\n\r]+)", owner_sec)
    if addr_match:
        addr = addr_match.group(1).strip()
        # 裁切掉後面可能多連進來的欄位標籤
        addr = re.split(r"(?:權利範圍|統一編號|權狀字號)", addr)[0].strip()

        if "***" in addr or "隱匿" in addr:
            data["戶籍地址"] = "隱匿"
        elif len(addr) > 2:
            data["戶籍地址"] = addr
        else:
            data["戶籍地址"] = "抓取錯誤"
    else:
        data["戶籍地址"] = "抓取錯誤"

    return data

# -------------------------------------------------------------
# 介面展示與批次匯出
# -------------------------------------------------------------
if uploaded_files:
    results = []

    with st.spinner(f"正在整理 {len(uploaded_files)} 份物件資料..."):
        for f in uploaded_files:
            try:
                info = parse_transcript_pdf(f)
                results.append(info)
            except Exception as e:
                st.error(f"檔案 {f.name} 處理失敗：{e}")

    if results:
        st.success(f"✅ 成功整理 {len(results)} 筆精耕資料！")
        df = pd.DataFrame(results)

        # 僅保留你指定的 5 大欄位順序
        columns_to_show = [
            "建物門牌", "總坪數", "主建物(坪)", "附屬(坪)", "公設(坪)",
            "車位標示", "所有權人", "戶籍地址"
        ]
        df = df[columns_to_show]

        st.subheader("📋 精耕物件清單")
        st.dataframe(df, use_container_width=True)

        # 提供乾淨的 Excel CSV 下載
        csv_data = df.to_csv(index=False).encode('utf-8-sig')
        st.download_button(
            label="📥 匯出精耕清單 (Excel CSV)",
            data=csv_data,
            file_name="精耕物件清單.csv",
            mime="text/csv"
        )
