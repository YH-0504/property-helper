import streamlit as st
import pdfplumber
import re
import pandas as pd

# 頁面基本設定
st.set_page_config(page_title="房產精耕謄本助手", layout="wide")

st.title("🏡 房產精耕小工具：建物謄本自動解析")
st.write("上傳建物第二類謄本 PDF，自動幫你計算坪數與提取關鍵資訊！")

# 1. 檔案上傳區
uploaded_file = st.file_uploader("請拖曳或上傳建物謄本 (PDF)", type=["pdf"])

def parse_transcript_pdf(file):
    """ 解析台灣建物謄本文字內容 """
    text = ""
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                text += t + "\n"

    data = {
        "門牌": "未識別",
        "建號": "未識別",
        "建築完成日": "未識別",
        "主建物面積(m²)": 0.0,
        "主建物(坪)": 0.0,
        "附屬建物面積(m²)": 0.0,
        "附屬建物(坪)": 0.0,
        "總登記面積(m²)": 0.0,
        "總面積(坪)": 0.0,
        "所有權人": "未識別",
        "登記住址": "未識別"
    }

    # 門牌提取
    addr_match = re.search(r"建物門牌[：:\s]+([^\n\r]+)", text)
    if addr_match:
        data["門牌"] = addr_match.group(1).strip()

    # 建號提取
    no_match = re.search(r"建\s*號[：:\s]+([^\n\r]+)", text)
    if no_match:
        data["建號"] = no_match.group(1).strip()

    # 建築完成日
    date_match = re.search(r"建築完成日期[：:\s]+([^\n\r]+)", text)
    if date_match:
        data["建築完成日"] = date_match.group(1).strip()

    # 面積計算 (平方公尺 -> 坪數，乘以 0.3025)
    # 抓取「層次面積」
    main_area_match = re.search(r"層次面積[：:\s]+([\d\.]+)", text)
    if main_area_match:
        m2 = float(main_area_match.group(1))
        data["主建物面積(m²)"] = m2
        data["主建物(坪)"] = round(m2 * 0.3025, 2)

    # 附屬建物（陽台、雨遮等）
    sub_area_match = re.search(r"(?:陽台|雨遮|平台)[：:\s]+([\d\.]+)", text)
    if sub_area_match:
        m2 = float(sub_area_match.group(1))
        data["附屬建物面積(m²)"] = m2
        data["附屬建物(坪)"] = round(m2 * 0.3025, 2)

    # 總面積
    total_area_match = re.search(r"總面積[：:\s]+([\d\.]+)", text)
    if total_area_match:
        m2 = float(total_area_match.group(1))
        data["總登記面積(m²)"] = m2
        data["總面積(坪)"] = round(m2 * 0.3025, 2)
    else:
        # 若未直接標記總面積，自動加總主建與附屬
        data["總面積(坪)"] = round(data["主建物(坪)"] + data["附屬建物(坪)"], 2)

    # 所有權人與住址 (二類謄本常見格式)
    owner_match = re.search(r"所有權人[：:\s]+([^\n\r]+)", text)
    if owner_match:
        data["所有權人"] = owner_match.group(1).strip()

    res_match = re.search(r"住\s*址[：:\s]+([^\n\r]+)", text)
    if res_match:
        data["登記住址"] = res_match.group(1).strip()

    return data, text

# 2. 處理與展示
if uploaded_file is not None:
    with st.spinner("正在解析謄本內容..."):
        try:
            info, raw_text = parse_transcript_pdf(uploaded_file)
            st.success("✅ 解析成功！")

            # 轉為 DataFrame 表格顯示
            df = pd.DataFrame([info])
            st.subheader("📊 整理結果預覽")
            st.dataframe(df)

            # 下載按鈕 (直接存成 Excel 格式相容的 CSV)
            csv = df.to_csv(index=False).encode('utf-8-sig')
            st.download_button(
                label="📥 下載為 Excel (CSV 檔)",
                data=csv,
                file_name="謄本整理結果.csv",
                mime="text/csv",
            )

            # 摺疊區塊：可查看原始 PDF 文字（方便除錯對照）
            with st.expander("查看 PDF 原始抓取文字"):
                st.text(raw_text)

        except Exception as e:
            st.error(f"解析發生錯誤：{e}")
