import streamlit as st
import pdfplumber
import pypdfium2 as pdfium
import pytesseract
from PIL import Image
import re
import pandas as pd
import io

# 1. 頁面基本配置
st.set_page_config(
    page_title="房產精耕謄本助手 Pro",
    page_icon="🏢",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# 2. 注入現代高階商務 CSS 樣式
st.markdown("""
<style>
    /* 引入現代無襯線字型 */
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;600;700&family=Noto+Sans+TC:wght@400;500;700&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Plus Jakarta Sans', 'Noto Sans TC', sans-serif;
    }

    /* 主背景微漸層 */
    .stApp {
        background: linear-gradient(180deg, #F8FAFC 0%, #F1F5F9 100%);
    }

    /* 頂部 Hero Banner */
    .hero-container {
        background: linear-gradient(135deg, #1E293B 0%, #0F172A 100%);
        border-radius: 16px;
        padding: 36px 40px;
        color: #FFFFFF;
        margin-bottom: 24px;
        box-shadow: 0 10px 25px -5px rgba(15, 23, 42, 0.1), 0 8px 10px -6px rgba(15, 23, 42, 0.1);
        border: 1px solid rgba(255, 255, 255, 0.1);
    }
    
    .hero-badge {
        display: inline-block;
        background: rgba(14, 165, 233, 0.2);
        color: #38BDF8;
        border: 1px solid rgba(56, 189, 248, 0.3);
        padding: 4px 12px;
        border-radius: 9999px;
        font-size: 0.8rem;
        font-weight: 600;
        margin-bottom: 12px;
        letter-spacing: 0.5px;
    }

    .hero-title {
        font-size: 2.2rem;
        font-weight: 700;
        margin: 0;
        letter-spacing: -0.5px;
        background: linear-gradient(120deg, #FFFFFF 30%, #94A3B8 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }

    .hero-desc {
        color: #94A3B8;
        font-size: 1rem;
        margin-top: 8px;
        margin-bottom: 0;
    }

    /* 上傳區域美化 */
    [data-testid="stFileUploader"] {
        background: #FFFFFF;
        border-radius: 16px;
        padding: 24px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
        border: 1px solid #E2E8F0;
        transition: all 0.2s ease;
    }
    [data-testid="stFileUploader"]:hover {
        border-color: #0EA5E9;
        box-shadow: 0 10px 15px -3px rgba(14, 165, 233, 0.1);
    }

    /* 數據統計小卡片 (Metric Cards) */
    .stat-card {
        background: #FFFFFF;
        border-radius: 14px;
        padding: 20px 24px;
        border: 1px solid #E2E8F0;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.02);
        display: flex;
        flex-direction: column;
        gap: 6px;
    }
    .stat-label {
        font-size: 0.85rem;
        color: #64748B;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    .stat-value {
        font-size: 1.8rem;
        font-weight: 700;
        color: #0F172A;
    }

    /* 下載按鈕強化 */
    .stDownloadButton > button {
        background: linear-gradient(135deg, #0EA5E9 0%, #0284C7 100%) !important;
        color: white !important;
        font-weight: 600 !important;
        font-size: 1rem !important;
        padding: 12px 28px !important;
        border-radius: 10px !important;
        border: none !important;
        box-shadow: 0 4px 14px rgba(14, 165, 233, 0.3) !important;
        transition: all 0.2s ease !important;
    }
    .stDownloadButton > button:hover {
        transform: translateY(-1px);
        box-shadow: 0 6px 20px rgba(14, 165, 233, 0.4) !important;
    }

    /* 隱藏 Streamlit 預設多餘頂部元件 */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

# 3. 頁首橫幅區塊
st.markdown("""
<div class="hero-container">
    <div class="hero-badge">OFFLINE OCR PRO</div>
    <h1 class="hero-title">建物謄本・電傳自動化精耕分析儀</h1>
    <p class="hero-desc">支援批次解析華安電傳與官方地政謄本，自動完成：門牌拼接、坪數拆解、車位萃取、稱謂判定與防護欄位精準定位。</p>
</div>
""", unsafe_allow_html=True)

# 4. 上傳區
uploaded_files = st.file_uploader(
    "拖曳或選取謄本 PDF 檔案進行批次萃取",
    type=["pdf"],
    accept_multiple_files=True,
    help="支援單檔或一次上傳數十份謄本 PDF"
)

def get_address_by_coordinates(file_bytes, page_idx=1):
    """ 利用『地址』文字座標精確定位右側區域進行 OCR """
    try:
        addr_box = None
        pdf_stream = io.BytesIO(file_bytes)
        with pdfplumber.open(pdf_stream) as pdf:
            target_p = pdf.pages[page_idx] if len(pdf.pages) > page_idx else pdf.pages[-1]
            page_w = target_p.width
            page_h = target_p.height
            words = target_p.extract_words()
            for w in words:
                if "地址" in w["text"] or "住址" in w["text"]:
                    addr_box = w
                    break
        
        pdf_doc = pdfium.PdfDocument(file_bytes)
        target_p_img = pdf_doc[page_idx if len(pdf_doc) > page_idx else len(pdf_doc) - 1]
        scale = 3.0
        pil_img = target_p_img.render(scale=scale).to_pil()
        img_w, img_h = pil_img.size

        if addr_box:
            scale_x = img_w / page_w
            scale_y = img_h / page_h
            x0 = int(addr_box["x1"] * scale_x) + 5
            y0 = int((addr_box["top"] - 3) * scale_y)
            x1 = int(img_w * 0.92)
            y1 = int((addr_box["bottom"] + 5) * scale_y)
            crop_rect = (x0, y0, x1, y1)
        else:
            crop_rect = (int(img_w * 0.22), int(img_h * 0.28), int(img_w * 0.90), int(img_h * 0.45))

        cropped = pil_img.crop(crop_rect)
        gray = cropped.convert('L')
        bw = gray.point(lambda x: 0 if x < 180 else 255, '1')
        
        text = pytesseract.image_to_string(bw, lang='chi_tra+eng', config='--psm 7')
        clean_text = re.sub(r"[\s\|\r\n]+", "", text)
        clean_text = re.sub(r"^(?:地址|住址)[：:\s]*", "", clean_text)
        
        if any(star in clean_text for star in ["***", "＊＊＊"]) or "隱匿" in clean_text:
            return "隱匿"
        
        if len(clean_text) >= 4 and not any(k in clean_text for k in ["查詢時間", "資料來源", "登記次序", "權利範圍"]):
            return clean_text
            
        return "隱匿"
    except Exception as e:
        return "辨識錯誤"

def parse_transcript_fast(file):
    file_bytes = file.read()
    file_stream = io.BytesIO(file_bytes)

    pages_text = []
    with pdfplumber.open(file_stream) as pdf:
        for p in pdf.pages:
            t = p.extract_text()
            pages_text.append(t if t else "")

    full_text = "\n".join(pages_text)

    # 全形轉半形
    half_text = ""
    for char in full_text:
        code = ord(char)
        if 0xFF01 <= code <= 0xFF5E:
            half_text += chr(code - 0xFEE0)
        elif code == 0x3000:
            half_text += " "
        else:
            half_text += char

    clean_full = re.sub(r"[\|\t]", " ", half_text)
    lines = [re.sub(r"\s+", " ", line).strip() for line in clean_full.split("\n") if line.strip()]

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

    # 1. 門牌組合
    city_district = ""
    region_match = re.search(r"([^\d\n\r\s]{2,3}(?:市|縣))\s*([^\d\n\r\s]{1,4}(?:區|鄉|鎮|市))", clean_full)
    if region_match:
        city_district = region_match.group(1).replace(" ", "") + region_match.group(2).replace(" ", "")

    raw_doorplate = ""
    for i, line in enumerate(lines):
        if "建物門牌" in line:
            after_label = re.sub(r"^.*?建物門牌[：:\s]*", "", line).strip()
            if len(after_label) > 1:
                raw_doorplate = after_label
                break
            elif i + 1 < len(lines):
                raw_doorplate = lines[i+1].strip()
                break

    raw_doorplate = raw_doorplate.replace(" ", "")
    if raw_doorplate:
        if any(c in raw_doorplate for c in ["市", "縣"]):
            data["建物門牌"] = raw_doorplate
        else:
            if region_match and region_match.group(2) in raw_doorplate:
                data["建物門牌"] = f"{region_match.group(1)}{raw_doorplate}"
            else:
                data["建物門牌"] = f"{city_district}{raw_doorplate}"

    # 2. 坪數
    main_m2 = 0.0
    main_match = re.search(r"層次面積\s*([\d\.]+)\s*平方公尺", clean_full)
    if main_match:
        main_m2 = float(main_match.group(1))
    data["主建物(坪)"] = round(main_m2 * 0.3025, 2)

    sub_m2 = 0.0
    sub_matches = re.findall(r"(?:陽台|露台|雨遮|平台|花台)[^\d\n\r]*?面積\s*([\d\.]+)\s*平方公尺", clean_full)
    if sub_matches:
        sub_m2 = sum([float(m) for m in sub_matches])
    data["附屬(坪)"] = round(sub_m2 * 0.3025, 2)

    pub_m2 = 0.0
    linear_text = clean_full.replace("\n", " ")
    pub_matches = re.findall(r"建號\s*([\d\.]+)\s*平方公\s*尺.*?權利範圍\s*(\d+)\s*分之\s*(\d+)", linear_text)
    for p_area, denom, numer in pub_matches:
        try:
            pub_m2 += float(p_area) * (float(numer) / float(denom))
        except:
            pass
    data["公設(坪)"] = round(pub_m2 * 0.3025, 2)
    data["總坪數"] = round(data["主建物(坪)"] + data["附屬(坪)"] + data["公設(坪)"], 2)

    # 3. 車位
    parking_match = re.search(r"(?:編號|車位)[：:\s]*([A-Za-z0-9\-\_]+号|[A-Za-z0-9\-\_]+號|[B|b]\d+[\s\-]*(?:號)?\d*)", clean_full)
    if not parking_match:
        parking_match = re.search(r"(地下一層|地下二層|地下三層|地下四層|地下五層|B[1-5])[^\n\r]*?(?:車位|編號)[：:\s]*([^\n\r\s]+)", clean_full)
        if parking_match:
            data["車位標示"] = f"{parking_match.group(1)} {parking_match.group(2)}"
    else:
        data["車位標示"] = parking_match.group(1).strip()

    # 4. 姓名性別
    owner_sec = clean_full
    owner_page_idx = 1
    for idx, pt in enumerate(pages_text):
        if "所有權" in pt:
            owner_page_idx = idx
            owner_sec = pt
            break

    raw_name = ""
    name_m = re.search(r"所有權人[：:\s\n]*([^\d\n\r\s]+)", owner_sec)
    if name_m:
        raw_name = re.sub(r"[\*＊]+", "", name_m.group(1)).strip()

    title = ""
    id_m = re.search(r"([A-Za-z])\s*([12])[\d\*＊]{2,}", owner_sec)
    if id_m:
        code = id_m.group(2)
        if code == "1":
            title = "先生"
        elif code == "2":
            title = "女士"

    if raw_name:
        data["所有權人"] = raw_name + title

    # 5. 戶籍地址
    data["戶籍地址"] = get_address_by_coordinates(file_bytes, page_idx=owner_page_idx)

    return data

# 5. 執行分析與精美呈現
if uploaded_files:
    results = []
    with st.spinner("⚡ 正在解析建物謄本資料，請稍候..."):
        for f in uploaded_files:
            try:
                info = parse_transcript_fast(f)
                results.append(info)
            except Exception as e:
                st.error(f"檔案 {f.name} 處理失敗：{e}")

    if results:
        df = pd.DataFrame(results)
        columns_to_show = [
            "建物門牌", "總坪數", "主建物(坪)", "附屬(坪)", "公設(坪)",
            "車位標示", "所有權人", "戶籍地址"
        ]
        df = df[columns_to_show]

        st.markdown("<div style='height: 16px;'></div>", unsafe_allow_html=True)
        
        # 儀表板小卡片（KPI Metrics）
        col1, col2, col3 = st.columns(3)
        with col1:
            st.markdown(f"""
            <div class="stat-card">
                <span class="stat-label">已解析戶數</span>
                <span class="stat-value">{len(df)} <span style="font-size: 1rem; font-weight: normal; color: #64748B;">筆</span></span>
            </div>
            """, unsafe_allow_html=True)
        with col2:
            total_sum = round(df["總坪數"].sum(), 2)
            st.markdown(f"""
            <div class="stat-card">
                <span class="stat-label">總建坪規模</span>
                <span class="stat-value">{total_sum} <span style="font-size: 1rem; font-weight: normal; color: #64748B;">坪</span></span>
            </div>
            """, unsafe_allow_html=True)
        with col3:
            parking_count = (df["車位標示"] != "無/未標示").sum()
            st.markdown(f"""
            <div class="stat-card">
                <span class="stat-label">具備車位戶數</span>
                <span class="stat-value">{parking_count} <span style="font-size: 1rem; font-weight: normal; color: #64748B;">筆</span></span>
            </div>
            """, unsafe_allow_html=True)

        st.markdown("<div style='height: 24px;'></div>", unsafe_allow_html=True)
        
        # 結果數據總表
        st.dataframe(
            df,
            use_container_width=True,
            height=min(450, 45 + len(df) * 38)
        )

        st.markdown("<div style='height: 16px;'></div>", unsafe_allow_html=True)

        # 匯出按鈕
        csv_data = df.to_csv(index=False).encode('utf-8-sig')
        st.download_button(
            label="📥 匯出精耕專用名冊 (Excel CSV)",
            data=csv_data,
            file_name="社區精耕謄本整理名冊.csv",
            mime="text/csv"
        )
