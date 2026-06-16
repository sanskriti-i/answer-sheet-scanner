import os
import json
import time
import io
import base64
import pandas as pd
import streamlit as st
from PIL import Image
from pydantic import BaseModel, Field
import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted

# --- 1. SET UP LOCAL STORAGE DIRECTORY ---
DOWNLOAD_DIR = "static_downloads"
if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

# --- 2. DATA ARCHITECTURE ---
class ScoreEntry(BaseModel):
    column_letter: str = Field(description="The letter header of the column ('a', 'b', 'c', or 'd') where a handwritten mark is visible.")
    score: str = Field(description="The explicit handwritten mark found inside this cell.")

class QuestionRow(BaseModel):
    question_number: str = Field(description="The printed index row number from 1 to 8 found in the 'Q. NO' column.")
    sub_parts: list[ScoreEntry] = Field(description="A list of only the sub-parts containing explicit handwritten marks.")
    question_total: str = Field(description="The handwritten row total mark found in the 'Total' column.")

class AdvancedAnswerSheetData(BaseModel):
    student_name: str = Field(description="The handwritten name of the student.")
    roll_number: str = Field(description="The handwritten roll number of the student.")
    marks_table: list[QuestionRow] = Field(description="The matrix containing exactly 8 rows for questions 1 through 8.")
    grand_total_marks: str = Field(description="Final handwritten total marks from the bottom of the table.")

# --- 3. GROUNDED ANCHORING PROMPT ---
prompt = (
    "You are an expert academic data extraction system. Your job is to strictly transcribe handwritten entries from an answer sheet grid into JSON.\n\n"
    "GRID LAYOUT RULES:\n"
    "- Column 1 ('Q. NO'): Contains pre-printed structural index labels (1 to 8). NEVER extract these as a student's score.\n"
    "- Columns 2-5 ('a', 'b', 'c', 'd'): Contain ONLY student marks handwritten by the examiner.\n"
    "- Column 6 ('Total'): Contains the handwritten total for that row.\n"
    "CRITICAL HANDLING FOR EMPTY CELLS:\n"
    "- If a column cell is blank, do not include its object inside the sub_parts array.\n"
    "- Convert handwritten fractional markings to tidy decimals (e.g., '½' to '0.5', '1½' to '1.5')."
)

# Streamlit Configurations
st.set_page_config(page_title="AI Verification Scanner", page_icon="📝", layout="wide")

st.title("📝 Student Marks Multi-Scanner with Continuous Saving")
st.write("Scan multiple sheets consecutively, verify them, and compile everything into a single downloadable Excel file.")

# Session state initialization
if "extracted_df" not in st.session_state:
    st.session_state.extracted_df = None
if "meta_data" not in st.session_state:
    st.session_state.meta_data = {}
if "master_data_list" not in st.session_state:
    st.session_state.master_data_list = []

# Sidebar Authentication
st.sidebar.markdown("### 🔑 Step 1: Authentication")
user_api_key = st.sidebar.text_input("Enter your Gemini API Key:", type="password")

if not user_api_key:
    st.sidebar.warning("⚠️ Please provide a valid Gemini API Key to unlock the scanner features.")
    st.stop()
else:
    genai.configure(api_key=user_api_key)
    st.sidebar.success("🔒 API Key locked in.")

# Existing File Integration
st.sidebar.write("---")
st.sidebar.markdown("### 📂 Step 2: Existing File (Optional)")
existing_excel_file = st.sidebar.file_uploader("Want to add to an existing sheet?", type=["xlsx"])

if existing_excel_file is not None and "file_loaded" not in st.session_state:
    try:
        loaded_df = pd.read_excel(existing_excel_file)
        st.session_state.master_data_list = loaded_df.to_dict(orient="records")
        st.session_state.file_loaded = True
    except Exception as e:
        st.sidebar.error(f"Error loading file: {e}")

with st.sidebar:
    st.write("---")
    st.header("🎛️ Input Controls")
    source_option = st.radio("Choose Input Method:", ("📤 Upload or Take Photo", "📸 Web Cam Preview"))
    
    raw_image = None
    if source_option == "📤 Upload or Take Photo":
        uploaded_file = st.file_uploader("Choose image...", type=["jpg", "jpeg", "png", "webp"])
        if uploaded_file is not None:
            raw_image = Image.open(uploaded_file)
    else:
        camera_file = st.camera_input("Align sheet cover inside frame")
        if camera_file is not None:
            raw_image = Image.open(camera_file)

col1, col2 = st.columns([1, 1.2])

with col1:
    if raw_image is not None:
        st.image(raw_image, caption="Current Answer Sheet Preview", use_column_width=True)
        
        if st.button("🚀 Step 3: Extract Marks via AI", type="primary"):
            with st.spinner("AI is evaluating handwriting and structure..."):
                try:
                    img = raw_image.copy()
                    if img.width > 1800:
                        w_percent = (1800 / float(img.width))
                        h_size = int((float(img.height) * float(w_percent)))
                        img = img.resize((1800, h_size), Image.Resampling.LANCZOS)
                    
                    model = genai.GenerativeModel('gemini-2.5-flash')
                    content_payload = [img, prompt]
                    
                    response = model.generate_content(
                        content_payload,
                        generation_config={
                            "response_mime_type": "application/json",
                            "response_schema": AdvancedAnswerSheetData,
                            "temperature": 0.1
                        }
                    )
                        
                    raw_json = json.loads(response.text)
                    st.session_state.meta_data = {
                        "Student Name": raw_json.get("student_name", ""),
                        "Roll Number": raw_json.get("roll_number", ""),
                        "Grand Total Sheet": raw_json.get("grand_total_marks", "")
                    }
                    
                    table_rows = []
                    for row in raw_json.get("marks_table", []):
                        q_num = str(row.get("question_number", "")).strip()
                        if q_num and q_num.isdigit():
                            row_dict = {"Q.No": f"Q{q_num}", "Part A": "", "Part B": "", "Part C": "", "Part d": "", "Total": row.get("question_total", "")}
                            for sub in row.get("sub_parts", []):
                                col_let = str(sub.get("column_letter", "")).strip().lower()
                                val = str(sub.get("score", "")).strip()
                                if col_let == 'a': row_dict["Part A"] = val
                                elif col_let == 'b': row_dict["Part B"] = val
                                elif col_let == 'c': row_dict["Part C"] = val
                                elif col_let == 'd': row_dict["Part d"] = val
                            table_rows.append(row_dict)
                    
                    st.session_state.extracted_df = pd.DataFrame(table_rows)
                    st.success("AI extraction completed!")
                except Exception as e:
                    st.error(f"Extraction Error: {e}")

with col2:
    if st.session_state.extracted_df is not None:
        st.header("🔍 Step 4: Review & Edit Grid")
        name_val = st.text_input("Student Name:", value=st.session_state.meta_data.get("Student Name"))
        roll_val = st.text_input("Roll Number:", value=st.session_state.meta_data.get("Roll Number"))
        grand_total_val = st.text_input("Calculated Grand Total:", value=st.session_state.meta_data.get("Grand Total Sheet"))
        
        st.write("### 📊 Question-wise Marks Table")
        edited_table_df = st.data_editor(st.session_state.extracted_df, hide_index=True, use_container_width=True)
        
        if st.button("➕ Step 5: Confirm & Append to Sheet List", type="secondary"):
            final_student_row = {"Student Name": name_val, "Roll Number": roll_val}
            for _, row in edited_table_df.iterrows():
                q_num_str = str(row["Q.No"]).replace("Q", "")
                final_student_row[f"{q_num_str}a"] = row["Part A"]
                final_student_row[f"{q_num_str}b"] = row["Part B"]
                final_student_row[f"{q_num_str}c"] = row["Part C"]
                final_student_row[f"{q_num_str}d"] = row["Part d"]
                final_student_row[f"Q{q_num_str}_Total"] = row["Total"]
            final_student_row["Grand Total Sheet"] = grand_total_val
            st.session_state.master_data_list.append(final_student_row)
            st.session_state.extracted_df = None
            st.session_state.meta_data = {}
            st.rerun()

    if len(st.session_state.master_data_list) > 0:
        st.write("---")
        st.header("📊 Compiled Multi-Student Sheet Preview")
        
        ordered_columns = ["Student Name", "Roll Number"]
        for i in range(1, 9):
            ordered_columns.extend([f"{i}a", f"{i}b", f"{i}c", f"{i}d", f"Q{i}_Total"])
        ordered_columns.append("Grand Total Sheet")
        
        master_df = pd.DataFrame(st.session_state.master_data_list)
        for col in ordered_columns:
            if col not in master_df.columns:
                master_df[col] = ""
        master_df = master_df[ordered_columns]
        st.dataframe(master_df, hide_index=True, use_container_width=True)
        
        # --- 💾 LOCAL DIRECTORY EXCEL RESERVATION ---
        filename = "compiled_student_marks.xlsx"
        local_file_path = os.path.join(DOWNLOAD_DIR, filename)
        
        with pd.ExcelWriter(local_file_path, engine='xlsxwriter') as writer:
            master_df.to_excel(writer, index=False, sheet_name='All Marks')
            
        with open(local_file_path, "rb") as f:
            excel_bytes = f.read()

        col_dl1, col_dl2 = st.columns([1, 1])
        with col_dl1:
            st.download_button(
                label="📥 Download Excel Sheet (PC/Laptop)", 
                data=excel_bytes, 
                file_name=filename, 
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", 
                type="secondary"
            )
            
            # Converted Mobile URL Link Patch
            b64_excel = base64.b64encode(excel_bytes).decode()
            mobile_download_url = f"data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,{b64_excel}"
            
            link_html = f'''
            <a href="{mobile_download_url}" download="{filename}" target="_blank" style="
                background-color: #24a0ed; 
                color: white; 
                padding: 10px 20px; 
                text-decoration: none; 
                font-weight: bold; 
                border-radius: 5px; 
                display: inline-block; 
                text-align: center; 
                margin-top: 10px; 
                width: 100%;
                box-shadow: 0px 4px 6px rgba(0,0,0,0.1);
            ">📱 Save Excel Sheet to Phone (Mobile Link)</a>
            '''
            st.markdown(link_html, unsafe_allow_html=True)
            
        with col_dl2:
            if st.button("🗑️ Clear Entire Session Data", use_container_width=True):
                st.session_state.master_data_list = []
                if "file_loaded" in st.session_state: del st.session_state.file_loaded
                st.rerun()
