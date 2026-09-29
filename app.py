import streamlit as st
import pdfplumber
import pypdfium2 as pdfium
import pytesseract
from PIL import Image, ImageEnhance
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
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;600;700&family=Noto+Sans+TC:wght@400;500;700&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Plus Jakarta Sans', 'Noto Sans TC', sans-serif;
    }
    .stApp {
        background: linear-gradient(180deg, #F8FAFC 0%, #F1F5F9 100%);
    }
    .hero-container {
        background: linear-gradient(135deg, #1E293B 0%, #0F172A 100%);
        border-radius: 16px;
        padding: 32px 36px;
        color: #FFFFFF;
        margin-bottom: 24px;
        box-shadow: 0 10px 25px -5px rgba(15, 23, 42, 0.1);
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
    }
    .hero-title {
        font-size: 2.1rem;
        font-weight: 700;
        margin: 0;
        color: #FFFFFF;
    }
    .hero-desc {
        color: #94A3B8;
        font-size: 0.95rem;
        margin-top: 8px;
        margin-bottom: 0;
    }
    [data-testid="stFileUploader"] {
        background: #FFFFFF;
        border-radius: 16px;
        padding: 24px;
        border: 1px solid #E2E8F0;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
    }
    .stat-card {
        background: #FFFFFF;
        border-radius: 14px;
        padding: 18px 22px;
        border: 1px solid #E2E8F0;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.02);
    }
    .stat-label {
        font-size: 0.8rem;
        color: #64748B;
        font-weight: 600;
        text-transform: uppercase;
    }
    .stat-value {
        font-size: 1.7rem;
        font-weight: 700;
        color: #0F172A;
    }
    .stDownloadButton > button {
        background: linear-gradient(135deg, #0EA5E9 0%, #0284C7 100%) !important;
        color: white !important;
        font-weight: 600 !important;
        border-radius: 10px !important;
        border: none !important;
        box-shadow: 0 4px 14px rgba(14, 165, 233, 0.3) !important;
    }
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

# 3. 頁首橫幅
st.markdown("""
<div class="hero-container">
    <div class="hero-badge">OFFLINE OCR PRO</div>
    <h1 class="hero-title">建物謄本・電傳自動化精耕分析儀</h1>
    <p class="hero-desc">強化版：多筆共有部分公設折行精算、其他登記事項停車位精確提取、地址圖像座標鎖定。</p>
</div>
""", unsafe_allow_html=True)

uploaded_files = st.file_uploader(
    "拖曳或選取謄本 PDF 檔案進行批次萃取",
    type=["pdf"],
    accept_multiple_files=True
)

def get_address_by_flexible_coordinates(file_bytes, page_idx=1):
    """ 透過統編與權利範圍夾角定位，精確擷取地址圖片並 OCR """
    debug_img = None
    debug_raw = ""
    try:
        pdf_stream = io.BytesIO(file_bytes)
        top_limit = None
        bottom_limit = None
        
        with pdfplumber.open(pdf_stream) as pdf:
            target_p = pdf.pages[page_idx] if len(pdf.pages) > page_idx else pdf.pages[-1]
            page_w = target_p.width
            page_h = target_p.height
            words = target_p.extract_words()
            
            for w in words:
                text = w["text"]
                if "地址" in text or "住址" in text:
                    top_limit = w["top"] - 4
                    bottom_limit = w["bottom"] + 4
                    break
                if "編號" in text or "統一" in text:
                    top_limit = w["bottom"]
                if "權利範圍" in text:
                    bottom_limit = w["top"]

        pdf_doc = pdfium.PdfDocument(file_bytes)
        target_p_img = pdf_doc[page_idx if len(pdf_doc) > page_idx else len(pdf_doc) - 1]
        scale = 3.5
        pil_img = target_p_img.render(scale=scale).to_pil()
        img_w, img_h = pil_img.size
        scale_y = img_h / page_h

        if top_limit and bottom_limit:
            y0 = int(top_limit * scale_y)
            y1 = int(bottom_limit * scale_y)
        elif top_limit:
            y0 = int(top_limit * scale_y)
            y1 = int((top_limit + 45) * scale_y)
        else:
            y0 = int(img_h * 0.34)
            y1 = int(img_h * 0.44)

        x0 = int(img_w * 0.22)
        x1 = int(img_w * 0.95)
        
        cropped = pil_img.crop((x0, y0, x1, y1))
        debug_img = cropped

        gray = cropped.convert('L')
        enhancer = ImageEnhance.Contrast(gray)
        enhanced = enhancer.enhance(2.0)
        
        ocr_result = pytesseract.image_to_string(enhanced, lang='chi_tra+eng', config='--psm 6')
        debug_raw = ocr_result
        
        clean_text = re.sub(r"[\s\|\r\n\t]+", "", ocr_result)
        clean_text = re.sub(r"^(?:地址|住址)[：:\s]*", "", clean_text)
        clean_text = re.sub(r"(?:權利範圍.*|統一編號.*)", "", clean_text)

        if any(star in clean_text for star in ["***", "＊＊＊"]) or "隱匿" in clean_text:
            return "隱匿", debug_img, debug_raw
        
        if len(clean_text) >= 4 and not any(k in clean_text for k in ["查詢時間", "資料來源", "登記次序"]):
            return clean_text, debug_img, debug_raw
            
        return "隱匿", debug_img, debug_raw
    except Exception as e:
        return "辨識錯誤", debug_img, str(e)

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

    # -------------------------------------------------------------
    # 1. 建物完整門牌 (補齊 臺南市東區 等)
    # -------------------------------------------------------------
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

    # -------------------------------------------------------------
    # 2. 面積計算 (主建、附屬、多筆公設持分精算)
    # -------------------------------------------------------------
    # 主建物 (層次面積)
    main_m2 = 0.0
    main_match = re.search(r"層次面積\s*([\d\.]+)\s*平方公\s*尺", clean_full)
    if not main_match:
        main_match = re.search(r"層次面積\s*([\d\.]+)", clean_full)
    if main_match:
        main_m2 = float(main_match.group(1))
    data["主建物(坪)"] = round(main_m2 * 0.3025, 2)

    # 附屬建物（陽台、露台、雨遮等）
    sub_m2 = 0.0
    sub_matches = re.findall(r"(?:陽台|露台|雨遮|平台|花台)[^\d\n\r]*?面積\s*([\d\.]+)\s*平方公\s*尺", clean_full)
    if not sub_matches:
        sub_matches = re.findall(r"(?:陽台|露台|雨遮|平台|花台)[^\d\n\r]*?面積\s*([\d\.]+)", clean_full)
    if sub_matches:
        sub_m2 = sum([float(m) for m in sub_matches])
    data["附屬(坪)"] = round(sub_m2 * 0.3025, 2)

    # 共有部分（公設持分加總：面積 * 分子 / 分母 * 0.3025）
    pub_m2 = 0.0
    # 將整段文字標準化為單行以消除「平方公\n尺」或多行間隔帶來的斷裂
    one_line_clean = " ".join(clean_full.split())
    
    # 匹配範例：建號967.07平方公尺...權利範圍 100000分之1629 或 建號 967.07 平方公 尺 ... 100000分之1629
    pub_patterns = re.findall(r"(?:共有部分|建號)\s*.*?([\d\.]+)\s*平方公\s*尺.*?權利範圍\s*(\d+)\s*分之\s*(\d+)", one_line_clean)
    
    if not pub_patterns:
        # 備用匹配：有些電傳只寫「建號 00865-000 967.07 100000分之1629」
        pub_patterns = re.findall(r"建號[^\d]*?[\d\-]+\s+([\d\.]+).*?權利範圍\s*(\d+)\s*分之\s*(\d+)", one_line_clean)

    for p_area, denom, numer in pub_patterns:
        try:
            pub_m2 += float(p_area) * (float(numer) / float(denom))
        except:
            pass
    
    data["公設(坪)"] = round(pub_m2 * 0.3025, 2)
    data["總坪數"] = round(data["主建物(坪)"] + data["附屬(坪)"] + data["公設(坪)"], 2)

    # -------------------------------------------------------------
    # 3. 車位標示 (特別針對第一頁共有部分下方「其他登記事項」中註記的車位)
    # -------------------------------------------------------------
    parking_found = ""
    
    # 優先從「其他登記事項」搜尋「含停車位...」
    # 格式可能如：含停車位編號：地下一層車位編號B1-12號、含停車位編號B4-105
    p_match1 = re.search(r"(?:含停車位|停車位編號|車位編號)[：:\s]*([^\n\r，,；;]+)", clean_full)
    if p_match1:
        parking_found = p_match1.group(1).strip()
    
    # 備用：若上述沒抓到，搜尋地下室層次或 B1~B5 編號
    if not parking_found:
        p_match2 = re.search(r"(地下一層|地下二層|地下三層|地下四層|地下五層|B[1-5])[^\n\r，,；;]*?(?:車位|編號)[：:\s]*([^\n\r\s，,；;]+)", clean_full)
        if p_match2:
            parking_found = f"{p_match2.group(1)} {p_match2.group(2)}".strip()
            
    # 備用：抓「B4-105」或類似號碼
    if not parking_found:
        p_match3 = re.search(r"([B|b][1-5][\s\-]*(?:號)?\d+)", clean_full)
        if p_match3:
            parking_found = p_match3.group(1).strip()

    if parking_found:
        # 去除多餘空格或標點
        parking_found = re.sub(r"^含", "", parking_found).strip()
        data["車位標示"] = parking_found
    else:
        data["車位標示"] = "無/未標示"

    # -------------------------------------------------------------
    # 4. 所有權人姓名與性別
    # -------------------------------------------------------------
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

    # -------------------------------------------------------------
    # 5. 戶籍地址辨識
    # -------------------------------------------------------------
    addr_val, dbg_img, dbg_raw = get_address_by_flexible_coordinates(file_bytes, page_idx=owner_page_idx)
    data["戶籍地址"] = addr_val

    return data, dbg_img, dbg_raw

# 5. 執行分析
if uploaded_files:
    results = []
    debug_info = {}

    with st.spinner("⚡ 正在解析建物謄本資料，請稍候..."):
        for f in uploaded_files:
            try:
                info, dbg_img, dbg_raw = parse_transcript_fast(f)
                results.append(info)
                debug_info[f.name] = {"img": dbg_img, "raw": dbg_raw}
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
        
        # 儀表板
        col1, col2, col3 = st.columns(3)
        with col1:
            st.markdown(f"""
            <div class="stat-card">
                <span class="stat-label">已解析戶數</span>
                <span class="stat-value">{len(df)} <span style="font-size: 1rem; color: #64748B;">筆</span></span>
            </div>
            """, unsafe_allow_html=True)
        with col2:
            total_sum = round(df["總坪數"].sum(), 2)
            st.markdown(f"""
            <div class="stat-card">
                <span class="stat-label">總建坪規模</span>
                <span class="stat-value">{total_sum} <span style="font-size: 1rem; color: #64748B;">坪</span></span>
            </div>
            """, unsafe_allow_html=True)
        with col3:
            parking_count = (df["車位標示"] != "無/未標示").sum()
            st.markdown(f"""
            <div class="stat-card">
                <span class="stat-label">具備車位戶數</span>
                <span class="stat-value">{parking_count} <span style="font-size: 1rem; color: #64748B;">筆</span></span>
            </div>
            """, unsafe_allow_html=True)

        st.markdown("<div style='height: 24px;'></div>", unsafe_allow_html=True)
        
        # 結果數據表
        st.dataframe(df, use_container_width=True, height=min(450, 45 + len(df) * 38))

        st.markdown("<div style='height: 16px;'></div>", unsafe_allow_html=True)

        csv_data = df.to_csv(index=False).encode('utf-8-sig')
        st.download_button(
            label="📥 匯出精耕專用名冊 (Excel CSV)",
            data=csv_data,
            file_name="社區精耕謄本整理名冊.csv",
            mime="text/csv"
        )

        with st.expander("🔍 查看地址裁切與 OCR 辨識過程 (若地址有誤可在此確認)"):
            for fname, d in debug_info.items():
                st.write(f"**檔案：{fname}**")
                if d["img"]:
                    st.image(d["img"], caption="系統自動裁切出的地址影像區域", width=500)
                st.write(f"OCR 原始吐出字串：`{d['raw']}`")
                st.markdown("---")
