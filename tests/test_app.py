import http.client
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from http.server import ThreadingHTTPServer
import sys
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server

class RecruitmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(); server.DB_PATH=Path(cls.temp.name)/'test.sqlite'; server.UPLOAD_DIR=Path(cls.temp.name)/'uploads'; server.initialize()
        cls.http=ThreadingHTTPServer(('127.0.0.1',0),server.App); cls.thread=threading.Thread(target=cls.http.serve_forever,daemon=True); cls.thread.start(); cls.port=cls.http.server_port
    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown(); cls.http.server_close(); cls.thread.join(); server.SESSIONS.clear(); cls.temp.cleanup()
    def request(self,method,path,data=None,headers=None):
        c=http.client.HTTPConnection('127.0.0.1',self.port); body=json.dumps(data).encode() if data is not None else None; h={'Content-Type':'application/json'} if body else {}; h.update(headers or {}); c.request(method,path,body,h); r=c.getresponse(); result=r.read(); return r.status,dict(r.getheaders()),result
    def submit_application(self,job_id,email,cv_data,filename='candidate.pdf'):
        boundary='brightcore-test-boundary'
        fields={'job_id':str(job_id),'full_name':'Test Candidate','email':email,'phone':'12345678','cover_note':'Interested in this role.'}
        parts=[]
        for name,value in fields.items():
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="cv"; filename="{filename}"\r\nContent-Type: application/pdf\r\n\r\n'.encode())
        parts.extend((cv_data,f'\r\n--{boundary}--\r\n'.encode()))
        body=b''.join(parts)
        connection=http.client.HTTPConnection('127.0.0.1',self.port)
        connection.request('POST','/api/applications',body,{'Content-Type':f'multipart/form-data; boundary={boundary}'})
        response=connection.getresponse(); return response.status,response.read()
    def test_seeded_admin_password_is_hashed(self):
        with server.connect() as db: stored=db.execute('SELECT password_hash FROM admins WHERE username=?',('admin',)).fetchone()[0]
        self.assertNotIn('BrightCore2026!',stored); self.assertTrue(server.password_matches('BrightCore2026!',stored))
    @patch.dict(os.environ,{'SMTP_HOST':'smtp.gmail.com','SMTP_FROM':'recruitment@example.test','SMTP_USERNAME':'admin@example.test','SMTP_PASSWORD':''})
    def test_email_reports_missing_smtp_password(self):
        self.assertEqual(server.send_applicant_email('candidate@example.test','Status update','Hello.'),'missing_credentials')
    @patch.dict(os.environ,{'SMTP_HOST':'smtp.example.test','SMTP_PORT':'587','SMTP_FROM':'careers@brightcore.example','SMTP_FROM_NAME':'BrightCore Recruitment Team','SMTP_USERNAME':'','SMTP_PASSWORD':'','SMTP_STARTTLS':'false'})
    @patch('server.smtplib.SMTP')
    def test_applicant_email_uses_configured_sender_and_recipient(self,mock_smtp):
        connection=mock_smtp.return_value.__enter__.return_value
        result=server.send_applicant_email('candidate@example.test','Interview shortlist','Dear candidate, congratulations.')
        self.assertEqual(result,'sent')
        sent=connection.send_message.call_args.args[0]
        self.assertEqual(sent['To'],'candidate@example.test')
        self.assertEqual(sent['From'],'BrightCore Recruitment Team <careers@brightcore.example>')
        self.assertIn('congratulations',sent.get_content())
    def test_public_jobs_hide_closed_roles(self):
        with server.connect() as db: db.execute("UPDATE jobs SET status='Closed' WHERE id=1")
        status,_,body=self.request('GET','/api/jobs'); self.assertEqual(status,200); self.assertNotIn(1,[j['id'] for j in json.loads(body)])
    def test_three_sample_jobs_are_seeded(self):
        with server.connect() as db: titles={row[0] for row in db.execute('SELECT title FROM jobs')}
        self.assertTrue({'Senior Product Designer','Backend Engineer','People Operations Associate'}.issubset(titles))
    def test_public_jobs_page_includes_search(self):
        status,_,body=self.request('GET','/')
        self.assertEqual(status,200)
        self.assertIn(b'id="job-search"',body)
    def test_admin_routes_require_login_and_session_is_issued(self):
        status,_,_=self.request('GET','/api/admin/jobs'); self.assertEqual(status,401)
        status,headers,_=self.request('POST','/api/login',{'username':'admin','password':'BrightCore2026!'}); self.assertEqual(status,200); self.assertIn('HttpOnly',headers['Set-Cookie'])
    def test_application_status_can_be_changed_by_admin(self):
        with server.connect() as db:
            db.execute("INSERT INTO applications(job_id,full_name,email,phone,cover_note,cv_filename,cv_path) VALUES(2,'Status Candidate','status@example.com','12345678','','cv.pdf','private')")
            application_id=db.execute('SELECT id FROM applications WHERE email=?',('status@example.com',)).fetchone()[0]
        _,headers,_=self.request('POST','/api/login',{'username':'admin','password':'BrightCore2026!'})
        cookie=headers['Set-Cookie'].split(';',1)[0]
        status,_,_=self.request('PATCH',f'/api/admin/applications/{application_id}',{'status':'Rejected','note':'Role requirements changed.','rejection_message':'Thank you for applying; we selected another candidate.'},{'Cookie':cookie})
        self.assertEqual(status,200)
        with server.connect() as db: row=db.execute('SELECT status,note,rejection_message FROM applications WHERE id=?',(application_id,)).fetchone()
        self.assertEqual((row['status'],row['note'],row['rejection_message']),('Rejected','Role requirements changed.','Thank you for applying; we selected another candidate.'))
        status,_,_=self.request('PATCH',f'/api/admin/applications/{application_id}',{'status':'Accepted','note':'Offer approved.','acceptance_message':'Congratulations, we would like to offer you the role.'},{'Cookie':cookie})
        self.assertEqual(status,200)
        with server.connect() as db: row=db.execute('SELECT status,acceptance_message FROM applications WHERE id=?',(application_id,)).fetchone()
        self.assertEqual((row['status'],row['acceptance_message']),('Accepted','Congratulations, we would like to offer you the role.'))
    def test_admin_applications_can_be_filtered_by_job(self):
        with server.connect() as db:
            db.execute("INSERT INTO applications(job_id,full_name,email,phone,cover_note,cv_filename,cv_path) VALUES(2,'Job Two Candidate','job-two@example.com','12345678','','two.pdf','private')")
            db.execute("INSERT INTO applications(job_id,full_name,email,phone,cover_note,cv_filename,cv_path) VALUES(3,'Job Three Candidate','job-three@example.com','12345678','','three.pdf','private')")
        _,headers,_=self.request('POST','/api/login',{'username':'admin','password':'BrightCore2026!'})
        cookie=headers['Set-Cookie'].split(';',1)[0]
        status,_,body=self.request('GET','/api/admin/applications?job_id=2',headers={'Cookie':cookie})
        self.assertEqual(status,200)
        rows=json.loads(body)
        self.assertTrue(rows)
        self.assertTrue(all(row['job_id']==2 for row in rows))
        self.assertIn('job-two@example.com',{row['email'] for row in rows})
    def test_duplicate_application_is_rejected_and_cv_private(self):
        with server.connect() as db:
            db.execute("UPDATE jobs SET status='Open',closing_date='2099-01-01' WHERE id=1")
            db.execute("INSERT INTO applications(job_id,full_name,email,phone,cover_note,cv_filename,cv_path) VALUES(1,'Test Candidate','person@example.com','12345678','','cv.pdf','private')")
        body=(b'--x\r\nContent-Disposition: form-data; name="job_id"\r\n\r\n1\r\n--x\r\nContent-Disposition: form-data; name="full_name"\r\n\r\nTest Candidate\r\n--x\r\nContent-Disposition: form-data; name="email"\r\n\r\nperson@example.com\r\n--x\r\nContent-Disposition: form-data; name="phone"\r\n\r\n12345678\r\n--x\r\nContent-Disposition: form-data; name="cv"; filename="cv.pdf"\r\nContent-Type: application/pdf\r\n\r\n%PDF-1.4 test\r\n--x--\r\n')
        # Submit a real multipart CV request and verify the database uniqueness rule.
        c=http.client.HTTPConnection('127.0.0.1',self.port); c.request('POST','/api/applications',body,{'Content-Type':'multipart/form-data; boundary=x'}); r=c.getresponse(); self.assertEqual(r.status,409)
        self.assertFalse((Path(server.UPLOAD_DIR)/'cv.pdf').exists())
    def test_successful_application_is_saved_as_pending(self):
        with server.connect() as db: db.execute("UPDATE jobs SET status='Open',closing_date='2099-01-01' WHERE id=2")
        status,body=self.submit_application(2,'success@example.com',b'%PDF-1.4\nvalid test pdf')
        self.assertEqual(status,201,json.loads(body))
        with server.connect() as db: row=db.execute('SELECT status,cv_path FROM applications WHERE email=?',('success@example.com',)).fetchone()
        self.assertEqual(row['status'],'Pending')
        self.assertTrue(Path(row['cv_path']).is_file())
    def test_closed_and_expired_jobs_reject_applications(self):
        with server.connect() as db:
            db.execute("UPDATE jobs SET status='Closed',closing_date='2099-01-01' WHERE id=2")
            db.execute("UPDATE jobs SET status='Open',closing_date='2000-01-01' WHERE id=3")
        for job_id,email in ((2,'closed@example.com'),(3,'expired@example.com')):
            status,body=self.submit_application(job_id,email,b'%PDF-1.4\nvalid test pdf')
            self.assertEqual(status,400,json.loads(body))
        with server.connect() as db: count=db.execute('SELECT COUNT(*) FROM applications WHERE email IN (?,?)',('closed@example.com','expired@example.com')).fetchone()[0]
        self.assertEqual(count,0)
    def test_cv_five_megabyte_limit_boundary(self):
        with server.connect() as db: db.execute("UPDATE jobs SET status='Open',closing_date='2099-01-01' WHERE id IN (2,3)")
        prefix=b'%PDF-1.4\n'
        at_limit=prefix+b'x'*(server.MAX_CV-len(prefix))
        status,body=self.submit_application(2,'limit@example.com',at_limit)
        self.assertEqual(status,201,json.loads(body))
        over_limit=prefix+b'x'*(server.MAX_CV+1-len(prefix))
        status,body=self.submit_application(3,'over-limit@example.com',over_limit)
        self.assertEqual(status,400,json.loads(body))

if __name__=='__main__': unittest.main()
