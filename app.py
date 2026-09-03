import streamlit as st
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
import pandas as pd
import json
import time

st.set_page_config(page_title="房產精耕謄本助手", layout="wide")

st.title("🏡 房產精耕小工具：謄本精準擷取 (高穩定版)")
st.write("透過原生多模態 AI 直接讀取謄本 PDF，自動攻克圖片戶籍地址、計算坪數與判斷稱謂！")

# 讀取 API Key (優先從 Secrets 抓，若無則在側邊欄輸入)
api_key = st.secrets.get("GEMINI_API_KEY", "")
if not api_key:
    api_key = st.sidebar.text_input("請輸入 Google Gemini API Key", type="password")

uploaded_files = st.file_uploader("請拖曳或上傳建物謄本/電傳 PDF (可複選多個)", type=["pdf"], accept_multiple_files=True)

class PropertyInfo(BaseModel):
    doorplate: str = Field(description="建物完整門牌，必須補齊縣市行政區，例如：臺南市東區東安路12巷22之3號")
    total_area: float = Field(description="總坪數（主建物+附屬+公設，若原載為平方公尺請乘0.3025換算為坪數）")
    main_area: float = Field(description="主建物坪數（層次面積換算為坪數）")
    sub_area: float = Field(description="附屬建物坪數（陽台、露台、雨遮等加總換算為坪數）")
    pub_area: float = Field(description="公設坪數（各筆共有部分面積乘持分後換算為坪數加總）")
    parking: str = Field(description="車位編號或標示，若無則填「無/未標示」")
    owner_name: str = Field(description="所有權人稱謂，例如：甘女士、王先生。去掉星號，並依統編身分證第一碼數字1判斷先生、2判斷女士")
    res_address: str = Field(description="所有權人的戶籍地址（建物所有權部裡的地址，若為圖片請精準辨識；若為星號則填「隱匿」）")

def extract_with_gemini(file_bytes, filename):
    client = genai.Client(api_key=api_key)
    
    prompt = """
    你是一位專業的台灣不動產專家。請審閱這份建物謄本（或地政電傳）PDF，精準提取以下 5 大資訊：
    1. 建物完整門牌：請結合文件標頭的縣市行政區（如臺南市東區）與門牌號碼，拼成完整地址。
    2. 坪數拆解（請全部換算為「坪」，平方公尺 * 0.3025）：
       - 主建物坪數（層次面積）
       - 附屬坪數（陽台、露台、雨遮加總）
       - 公設坪數（各筆共有部分建號之持分面積加總）
       - 總坪數（主建物 + 附屬 + 公設）
    3. 車位標示：若共有部分備註或其他登記事項有標註車位號（如 B4-105），請抓出；若無則填「無/未標示」。
    4. 所有權人姓名與稱謂：
       - 去除遮蔽星號（例如「甘**」轉為「甘」）。
       - 依統一編號/身分證字號第二碼（即英文後的第一位數字）：1 為「先生」、2 為「女士」。組合成「甘女士」或「王先生」。
    5. 戶籍地址：位於「建物所有權部」的「地址」欄位（注意：即使該欄位在 PDF 中為嵌入圖片，也請進行 OCR 精準識別出完整縣市市區路名門牌）。若被星號遮蔽則填「隱匿」。
    """

    # 優先使用最穩定的 1.5-flash，若遇 503 伺服器忙碌則自動嘗試 1.5-pro
    models_to_try = ['gemini-1.5-flash', 'gemini-1.5-pro']
    last_err = None

    for m_name in models_to_try:
        for attempt in range(2): # 每個模型最多重試兩次
            try:
                response = client.models.generate_content(
                    model=m_name,
                    contents=[
                        types.Part.from_bytes(
                            data=file_bytes,
                            mime_type='application/pdf'
                        ),
                        prompt
                    ],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=PropertyInfo,
                        temperature=0.1
                    )
                )
                res_dict = json.loads(response.text)
                return {
                    "建物門牌": res_dict.get("doorplate", "未識別"),
                    "總坪數": round(float(res_dict.get("total_area", 0.0)), 2),
                    "主建物(坪)": round(float(res_dict.get("main_area", 0.0)), 2),
                    "附屬(坪)": round(float(res_dict.get("sub_area", 0.0)), 2),
                    "公設(坪)": round(float(res_dict.get("pub_area", 0.0)), 2),
                    "車位標示": res_dict.get("parking", "無/未標示"),
                    "所有權人": res_dict.get("owner_name", "未識別"),
                    "戶籍地址": res_dict.get("res_address", "未識別")
                }
            except Exception as e:
                last_err = e
                time.sleep(1.5) # 稍作等待後重試
                continue

    raise last_err

if uploaded_files:
    if not api_key:
        st.error("⚠️ 請先在左側欄輸入 Gemini API Key，或在 Streamlit Secrets 中設定！")
    else:
        results = []
        with st.spinner(f"正在透過 AI 解析 {len(uploaded_files)} 份謄本資料..."):
            for f in uploaded_files:
                try:
                    f_bytes = f.read()
                    data = extract_with_gemini(f_bytes, f.name)
                    results.append(data)
                except Exception as e:
                    st.error(f"檔案 {f.name} 處理失敗：{e}")

        if results:
            st.success(f"✅ 成功整理 {len(results)} 筆資料！")
            df = pd.DataFrame(results)

            columns_to_show = [
                "建物門牌", "總坪數", "主建物(坪)", "附屬(坪)", "公設(坪)",
                "車位標示", "所有權人", "戶籍地址"
            ]
            df = df[columns_to_show]

            st.subheader("📋 精耕物件清單")
            st.dataframe(df, use_container_width=True)

            csv_data = df.to_csv(index=False).encode('utf-8-sig')
            st.download_button(
                label="📥 匯出精耕清單 (Excel CSV)",
                data=csv_data,
                file_name="精耕物件清單.csv",
                mime="text/csv"
            )
