import math
import sqlite3
import streamlit as st
import pandas as pd
import re
from PyPDF2 import PdfReader
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


def init_db():
    # Database Setup
    conn = sqlite3.connect("resumes.db")
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS jobs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        title TEXT,
                        description TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS resumes (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        job_id INTEGER,
                        filename TEXT UNIQUE,
                        content TEXT,
                        score REAL,
                        FOREIGN KEY(job_id) REFERENCES jobs(id))''')
    conn.commit()
    conn.close()


def clean_text(text):
    # Function to clean text
    text = text.lower()
    text = re.sub(r'[^a-zA-Z0-9\s]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def extract_section(text, section_name):
    # Function to extract specific sections from resume
    section_patterns = {
        "skills": r"(skills|technical skills|key skills)\s*:*(.*?)(?:\n\n|\Z)",
        "experience": r"(work experience|professional experience|employment history)\s*:*(.*?)(?:\n\n|\Z)",
        "education": r"(education|academic background|qualifications)\s*:*(.*?)(?:\n\n|\Z)"
    }
    match = re.search(
        section_patterns[section_name], text, re.IGNORECASE | re.DOTALL)
    return match.group(2).strip() if match else ""


def extract_text_from_pdf(file):
    # Function to extract text from PDF
    pdf_reader = PdfReader(file)
    text = " ".join([page.extract_text()
                    for page in pdf_reader.pages if page.extract_text()])
    return clean_text(text)


def sigmoid(x):
    return 1 / (1 + math.exp(-x))


def rank_resumes(job_desc, resumes):
    # Function to rank resumes dynamically based on job requirements
    vectorizer = TfidfVectorizer()
    job_skills = extract_section(job_desc, "skills") or job_desc
    job_experience = extract_section(job_desc, "experience") or job_desc
    job_education = extract_section(job_desc, "education") or job_desc
    job_skills_set = set(job_skills.split())

    scores = []
    for resume in resumes:
        resume_skills = extract_section(resume, "skills") or ""
        resume_experience = extract_section(resume, "experience") or ""
        resume_education = extract_section(resume, "education") or ""

        skills_score = cosine_similarity(vectorizer.fit_transform(
            [job_skills, resume_skills]))[0, 1] if resume_skills else 0
        experience_score = cosine_similarity(vectorizer.fit_transform(
            [job_experience, resume_experience]))[0, 1] if resume_experience else 0
        education_score = cosine_similarity(vectorizer.fit_transform(
            [job_education, resume_education]))[0, 1] if resume_education else 0

        # Boost score based on required skills presence
        resume_skills_set = set(resume_skills.split())
        skill_match_count = len(job_skills_set.intersection(resume_skills_set))
        # Increase weight dynamically per matched skill
        skill_boost = skill_match_count * 0.05

        total_score = sigmoid((0.4 * skills_score) + (0.4 *
                              experience_score) + (0.2 * education_score) + skill_boost)
        scores.append(total_score)

    return scores


if __name__ == "__main__":
    try:
        # Streamlit UI
        st.title("AI-Powered Resume Screening System")
        init_db()
        conn = sqlite3.connect("resumes.db")
        cursor = conn.cursor()

        # Admin: Create Job Posting
        st.sidebar.header("Admin Panel")
        with st.sidebar.form("create_job"):
            job_title = st.text_input("Job Title")
            job_desc = st.text_area("Job Description")
            submit_job = st.form_submit_button("Create Job")
            if submit_job and job_title and job_desc:
                cursor.execute("INSERT INTO jobs (title, description) VALUES (?, ?)",
                               (job_title, clean_text(job_desc)))
                conn.commit()
                st.success("Job created successfully!")

        # User: Upload Resume
        st.sidebar.header("Upload Resume")
        jobs = cursor.execute("SELECT id, title FROM jobs").fetchall()
        if jobs:
            job_options = {str(j[0]): j[1] for j in jobs}
            selected_job = st.sidebar.selectbox("Select Job", list(
                job_options.keys()), format_func=lambda x: job_options[x])
            uploaded_files = st.sidebar.file_uploader(
                "Upload Resume (PDF)", accept_multiple_files=True, type=['pdf'])
            if uploaded_files:
                for uploaded_file in uploaded_files:
                    text = extract_text_from_pdf(uploaded_file)
                    cursor.execute("INSERT INTO resumes (job_id, filename, content, score) VALUES (?, ?, ?, ?)", (
                        selected_job, uploaded_file.name, text, 0))
                    conn.commit()
                st.sidebar.success("Resumes uploaded successfully!")
        else:
            st.sidebar.warning("No job postings available. Create one first!")

        # Display Leaderboard
        st.header("Leaderboard")
        if jobs:
            selected_job_leaderboard = st.selectbox("Select Job to View Leaderboard", list(
                job_options.keys()), format_func=lambda x: job_options[x])
            job_desc = cursor.execute(
                "SELECT description FROM jobs WHERE id = ?", (selected_job_leaderboard,)).fetchone()[0]
            resumes = cursor.execute(
                "SELECT id, filename, content FROM resumes WHERE job_id = ?", (selected_job_leaderboard,)).fetchall()
            if resumes:
                resume_texts = [clean_text(r[2]) for r in resumes]
                scores = rank_resumes(job_desc, resume_texts)
                for idx, (r_id, filename, _) in enumerate(resumes):
                    cursor.execute(
                        "UPDATE resumes SET score = ? WHERE id = ?", (float(scores[idx]), r_id))
                conn.commit()
                leaderboard = pd.DataFrame(
                    resumes, columns=["ID", "Filename", "Content"])
                leaderboard["Score"] = scores
                leaderboard = leaderboard.sort_values(by="Score", ascending=False)[
                    ["Filename", "Score"]]
                st.table(leaderboard)
            else:
                st.warning("No resumes uploaded yet!")

        conn.close()
    except Exception as e:
        st.error(f"An error occurred: {e}")
