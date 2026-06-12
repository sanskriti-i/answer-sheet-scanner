import os
import json
import time
import io
import pandas as pd
import streamlit as st
from PIL import Image
from pydantic import BaseModel, Field
import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted

# 🟢 Data Structures for Gemini Structured Outputs
class QuestionRow(BaseModel):
    question_number: str = Field(description="The question number row from 1 to 8")
    part_a_marks: str = Field(description="Marks obtained in part a. Empty string if blank.")
    part_b_marks: str = Field(description="Marks obtained in part b. Empty string if blank.")
    part_c_marks: str = Field(description="Marks obtained in part c. Empty string if blank.")
    part_d_marks: str = Field(description="Marks obtained in part d. Empty string if blank.")
    question_total: str = Field(description="The row total marks as a simple number string.")

class AdvancedAnswerSheetData(BaseModel):
    student_name: str
    roll_number: str
    marks_table: list[QuestionRow]
    grand_total_marks: str = Field(description="Final total marks, converted to decimal format.")

prompt = (
    "Analyze this student answer sheet cover page carefully. "
    "Extract the handwritten Student Name, Roll Number, and the entire Marks table from Q.NO 1 to 8. "
    "Convert all fractions to standard decimals (e.g., ½ becomes 0.5)."
)

# 🟢 Streamlit Page Configurations
st.set_page_config(page_title="AI Verification Scanner", page_icon="📝", layout="wide")

# 🚀 CUSTOM CSS INJECTION FOR HIGH-RESOLUTION CAMERA VIEWS
st.markdown(
    """
    <style>
    video {
        image-rendering: -webkit-optimize-contrast !important;
        image-rendering: crisp-edges !important;
    }
    div[data-testid="stCameraInput"] canvas {
        width: 100% !important;
        height: auto !important;
        image-rendering: pixelated !important;
    }
    </style>
    """,
    unsafe_allow_html=True
)

st.title("📝 Student Marks Multi-Scanner with Continuous Saving")
st.write("Scan multiple sheets consecutively, verify them, and compile everything into a single downloadable Excel file.")

# 🟢 Session States to retain data across multiple scans
if "extracted_df" not in st.session_state:
    st.session_state.extracted_df = None
if "meta_data" not in st.session_state:
    st.session_state.meta_data = {}
if "master_data_list" not in st.session_state:
    st.session_state.master_data_list = []  # Holds the accumulated table rows for this session

# 🔑 SIDEBAR STEP 1: Force User to Provide Their Own API Key
st.sidebar.markdown("### 🔑 Step 1: Authentication")
user_api_key = st.sidebar.text_input(
    "Enter your Gemini API Key:", 
    type="password", 
    help="Get a free key from Google AI Studio. This key is processed locally and never stored permanently."
)

# Show a warning and stop execution if the user hasn't provided a key yet
if not user_api_key:
    st.sidebar.warning("⚠️ Please provide a valid Gemini API Key to unlock the scanner features.")
    st.info("👋 Welcome! To use this scanner app on your device, look at the sidebar on the left, paste your personal Gemini API Key into the input box, and hit Enter.")
    st.stop()  # Strictly halts the rest of the app execution until the condition is met
else:
    # Safely configure the library dynamically using the user's specific credentials
    genai.configure(api_key=user_api_key)
    st.sidebar.success("🔒 API Key locked in for this session.")

# 📁 STEP 2: Let user upload their existing progress file from their device
st.sidebar.write("---")
st.sidebar.markdown("### 📂 Step 2: Existing File (Optional)")
existing_excel_file = st.sidebar.file_uploader(
    "Want to add to an existing sheet? Select it here:", 
    type=["xlsx"]
)

# Load existing data into session state *once* when uploaded
if existing_excel_file is not None and "file_loaded" not in st.session_state:
    try:
        loaded_df = pd.read_excel(existing_excel_file)
        st.session_state.master_data_list = loaded_df.to_dict(orient="records")
        st.session_state.file_loaded = True
        st.sidebar.success(f"Loaded {len(loaded_df)} existing records successfully!")
    except Exception as e:
        st.sidebar.error(f"Error loading file: {e}")

# Sidebar for camera/upload controls
with st.sidebar:
    st.write("---")
    st.header("🎛️ Input Controls")
    source_option = st.radio("Choose Input Method:", ("📤 Upload or Take Photo", "📸 Web Cam Preview"))
    
    raw_image = None
    if source_option == "📤 Upload or Take Photo":
        uploaded_file = st.file_uploader("Choose image or take a clear photo...", type=["jpg", "jpeg", "png", "webp"])
        if uploaded_file is not None:
            raw_image = Image.open(uploaded_file)
    else:
        camera_file = st.camera_input("Align sheet cover inside frame")
        if camera_file is not None:
            raw_image = Image.open(camera_file)

# 🟢 Layout split into 2 columns: Left for Image, Right for Data Processing
col1, col2 = st.columns([1, 1.2])

with col1:
    if raw_image is not None:
        st.image(raw_image, caption="Current Answer Sheet Preview", use_column_width=True)
        
        # Trigger Extraction Button
        if st.button("🚀 Step 3: Extract Marks via AI", type="primary"):
            with st.spinner("AI is analyzing handwriting..."):
                try:
                    # Token Optimization
                    img = raw_image.copy()
                    if img.width > 1800:
                        w_percent = (1800 / float(img.width))
                        h_size = int((float(img.height) * float(w_percent)))
                        img = img.resize((1800, h_size), Image.Resampling.LANCZOS)
                    
                    # Pass the dynamic model setup
                    model = genai.GenerativeModel('gemini-2.5-flash')
                    
                    # Package configuration rules
                    content_payload = [img, prompt]
                    generation_config = genai.types.GenerationConfig(
                        response_mime_type="application/json", 
                        response_schema=AdvancedAnswerSheetData,
                        temperature=0.1, 
                    )
                    
                    # Safe Execution Loop for Rate Limits
                    response = None
                    for attempt in range(5):
                        try:
                            response = model.generate_content(content_payload, generation_config=generation_config)
                            break
                        except ResourceExhausted:
                            wait_time = (2 ** attempt)
                            st.warning(f"Rate limit hit. Retrying automatically in {wait_time} seconds...")
                            time.sleep(wait_time)
                    
                    if response is None:
                        raise Exception("Failed to get response from Gemini API after multiple retry attempts.")
                        
                    raw_json = json.loads(response.text)
                    
                    st.session_state.meta_data = {
                        "Student Name": raw_json.get("student_name", ""),
                        "Roll Number": raw_json.get("roll_number", ""),
                        "Grand Total Sheet": raw_json.get("grand_total_marks", "")
                    }
                    
                    # Build editable table row structure
                    table_rows = []
                    for row in raw_json.get("marks_table", []):
                        q_num = str(row.get("question_number", "")).strip()
                        if q_num and q_num.isdigit():
                            table_rows.append({
                                "Q.No": f"Q{q_num}",
                                "Part A": row.get("part_a_marks", ""),
                                "Part B": row.get("part_b_marks", ""),
                                "Part C": row.get("part_c_marks", ""),
                                "Part D": row.get("part_d_marks", ""),
                                "Total": row.get("question_total", "")
                            })
                    
                    st.session_state.extracted_df = pd.DataFrame(table_rows)
                    st.success("AI extraction completed! Review data on the right panel.")
                    
                except Exception as e:
                    # Catch authentication/wrong key errors specifically
                    if "401" in str(e) or "API key" in str(e):
                        st.error("❌ Authentication Failed: The API key you entered is invalid or deactivated. Please check it in the sidebar.")
                    else:
                        st.error(f"Extraction Error: {e}")

with col2:
    if st.session_state.extracted_df is not None:
        st.header("🔍 Step 4: Review & Edit Grid")
        st.info("💡 Review the current student data. Clicking 'Save Row' will add it to your compiled sheet.")
        
        # 1. Edit Student Name & Roll Number
        name_val = st.text_input("Student Name:", value=st.session_state.meta_data.get("Student Name"))
        roll_val = st.text_input("Roll Number:", value=st.session_state.meta_data.get("Roll Number"))
        grand_total_val = st.text_input("Calculated Grand Total:", value=st.session_state.meta_data.get("Grand Total Sheet"))
        
        # 2. Editable Data Grid for Marks Matrix
        st.write("### 📊 Question-wise Marks Table")
        edited_table_df = st.data_editor(st.session_state.extracted_df, hide_index=True, use_column_width=True)
        
        # 3. Compile Row Data
        if st.button("➕ Step 5: Confirm & Append to Sheet List", type="secondary"):
            final_student_row = {
                "Student Name": name_val,
                "Roll Number": roll_val
            }
            
            for _, row in edited_table_df.iterrows():
                q_num_str = str(row["Q.No"]).replace("Q", "")
                final_student_row[f"{q_num_str}a"] = row["Part A"]
                final_student_row[f"{q_num_str}b"] = row["Part B"]
                final_student_row[f"{q_num_str}c"] = row["Part C"]
                final_student_row[f"{q_num_str}d"] = row["Part D"]
                final_student_row[f"Q{q_num_str}_Total"] = row["Total"]
                
            final_student_row["Grand Total Sheet"] = grand_total_val
            
            st.session_state.master_data_list.append(final_student_row)
            st.success(f"🎉 Successfully added row for '{name_val}'!")
            
            st.session_state.extracted_df = None
            st.session_state.meta_data = {}
            st.rerun()

    # 🟢 Session Summary & Export Actions Area
    if len(st.session_state.master_data_list) > 0:
        st.write("---")
        st.header("📊 Compiled Multi-Student Sheet Preview")
        st.write(f"This spreadsheet contains **{len(st.session_state.master_data_list)}** rows accumulated during this session.")
        
        ordered_columns = ["Student Name", "Roll Number"]
        for i in range(1, 9):
            ordered_columns.extend([f"{i}a", f"{i}b", f"{i}c", f"{i}d", f"Q{i}_Total"])
        ordered_columns.append("Grand Total Sheet")
        
        master_df = pd.DataFrame(st.session_state.master_data_list)
        for col in ordered_columns:
            if col not in master_df.columns:
                master_df[col] = ""
        master_df = master_df[ordered_columns]
        use_column_width=True
        st.dataframe(master_df, hide_index=True, )
        
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
            master_df.to_excel(writer, index=False, sheet_name='All Marks')
        buffer.seek(0)
        
        col_dl1, col_dl2 = st.columns([1, 1])
        with col_dl1:
            st.download_button(
                label="📥 Download Compiled Master Excel Sheet",
                data=buffer,
                file_name="compiled_student_marks.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary"
            )
        with col_dl2:
            if st.button("🗑️ Clear Entire Session Data", type="secondary"):
                st.session_state.master_data_list = []
                if "file_loaded" in st.session_state:
                    del st.session_state.file_loaded
                st.rerun()
                
    elif st.session_state.extracted_df is None:
        st.info("Provide your API key and upload/capture an answer sheet to begin.")