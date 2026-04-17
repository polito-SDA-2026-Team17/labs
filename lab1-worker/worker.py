import os
import time
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

MONGODB_URI = os.getenv("MONGODB_URI")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL_SECONDS", 5))
SMTP_HOST = os.getenv("SMTP_HOST", "localhost")
SMTP_PORT = int(os.getenv("SMTP_PORT", 1025))
EMAIL_FROM = os.getenv("EMAIL_FROM", "worker@mzinga.io")

client = MongoClient(MONGODB_URI)
db = client.get_default_database()
communications = db.communications
users = db.users

def resolve_emails(references):
    if not references:
        return []
    
    emails = []
    for ref in references:
        if ref.get("relationTo") == "users":
            user_id = ref.get("value")
            user = users.find_one({"_id": user_id})
            if user and "email" in user:
                emails.append(user["email"])
    return emails

def serialize_ast(nodes):
    if not nodes:
        return ""
    
    html = ""
    for node in nodes:
        if "text" in node:
            text = node["text"]
            if node.get("bold"):
                text = f"<strong>{text}</strong>"
            if node.get("italic"):
                text = f"<em>{text}</em>"
            html += text
            continue

        children_html = serialize_ast(node.get("children", []))
        node_type = node.get("type")

        if node_type == "h1":
            html += f"<h1>{children_html}</h1>"
        elif node_type == "h2":
            html += f"<h2>{children_html}</h2>"
        elif node_type == "paragraph":
            html += f"<p>{children_html}</p>"
        elif node_type == "ul":
            html += f"<ul>{children_html}</ul>"
        elif node_type == "li":
            html += f"<li>{children_html}</li>"
        elif node_type == "link":
            url = node.get("url", "#")
            html += f'<a href="{url}">{children_html}</a>'
        else:
            html += children_html
            
    return html

def process_document(doc):
    doc_id = doc["_id"]
    
    try:
        to_emails = resolve_emails(doc.get("tos"))
        cc_emails = resolve_emails(doc.get("ccs"))
        bcc_emails = resolve_emails(doc.get("bccs"))

        if not to_emails:
            raise ValueError("Document has no valid 'to' recipients.")

        html_body = serialize_ast(doc.get("body", []))

        msg = MIMEMultipart()
        msg['From'] = EMAIL_FROM
        msg['To'] = ", ".join(to_emails)
        if cc_emails:
            msg['Cc'] = ", ".join(cc_emails)
        msg['Subject'] = doc.get("subject", "No Subject")

        msg.attach(MIMEText(html_body, 'html'))

        all_recipients = to_emails + cc_emails + bcc_emails

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.sendmail(EMAIL_FROM, all_recipients, msg.as_string())

        communications.update_one({"_id": doc_id}, {"$set": {"status": "sent"}})
        print(f"[{time.strftime('%X')}] Document {doc_id} processed and sent.")

    except Exception as e:
        communications.update_one({"_id": doc_id}, {"$set": {"status": "failed"}})
        print(f"[{time.strftime('%X')}] Document {doc_id} failed: {e}")

def main():
    print(f"Worker started. Polling MongoDB at interval: {POLL_INTERVAL}s")
    
    while True:
        doc = communications.find_one_and_update(
            {"status": "pending"},
            {"$set": {"status": "processing"}}
        )

        if doc:
            process_document(doc)
        else:
            time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    main()