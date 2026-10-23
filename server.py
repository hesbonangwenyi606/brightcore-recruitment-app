"""BrightCore recruitment app: dependency-free Python/SQLite HTTP server."""
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import smtplib
import sqlite3
import urllib.request
import urllib.parse
import time
from contextlib import contextmanager
from email.message import EmailMessage
from email.utils import formataddr
from email.parser import BytesParser
from email.policy import default
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).parent
DB_PATH = Path(os.environ.get('BRIGHTCORE_DB', ROOT / 'brightcore.sqlite3'))
UPLOAD_DIR = Path(os.environ.get('BRIGHTCORE_UPLOADS', ROOT / 'private_uploads'))
MAX_CV = 5 * 1024 * 1024
SESSIONS = {}
DATABASE_URL = os.environ.get('DATABASE_URL', '').strip()
SUPABASE_URL = os.environ.get('SUPABASE_URL', '').rstrip('/')
SUPABASE_SERVICE_ROLE_KEY = os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '')
SUPABASE_CV_BUCKET = os.environ.get('SUPABASE_CV_BUCKET', 'candidate-cvs')

def load_dotenv():
    env_file=ROOT/'.env'
    if not env_file.exists(): return
    for raw_line in env_file.read_text(encoding='utf-8').splitlines():
        line=raw_line.strip()
        if not line or line.startswith('#') or '=' not in line: continue
        key,value=line.split('=',1); key=key.strip(); value=value.strip()
        if len(value)>=2 and value[0]==value[-1] and value[0] in ('"',"'"): value=value[1:-1]
        if key: os.environ.setdefault(key,value)

load_dotenv()

@contextmanager
def connect():
    if DATABASE_URL:
        import psycopg
        from psycopg.rows import dict_row
        raw_db = psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=10, prepare_threshold=None)
        class PgConnection:
            def execute(self, sql, params=()):
                return raw_db.execute(sql.replace('?', '%s'), params)
            def executemany(self, sql, params):
                return raw_db.executemany(sql.replace('?', '%s'), params)
            def commit(self): return raw_db.commit()
            def rollback(self): return raw_db.rollback()
            def close(self): return raw_db.close()
        db = PgConnection()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
        return
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

def hash_password(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    return salt.hex() + ':' + hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 240000).hex()

def password_matches(password, stored):
    salt, _ = stored.split(':', 1)
    return hmac.compare_digest(hash_password(password, bytes.fromhex(salt)), stored)

def send_applicant_email(recipient, subject, body):
    if os.environ.get('EMAIL_DRY_RUN','').lower() in ('1','true','yes'):
        print(f"\n--- EMAIL DRY RUN ---\nTo: {recipient}\nSubject: {subject}\n\n{body}\n--- END EMAIL DRY RUN ---\n",flush=True)
        return 'simulated'
    resend_api_key=os.environ.get('RESEND_API_KEY','').strip()
    if resend_api_key:
        sender=os.environ.get('RESEND_FROM','').strip()
        if not sender: return 'not_configured'
        payload=json.dumps({'from':sender,'to':[recipient],'subject':subject,'text':body}).encode('utf-8')
        request=urllib.request.Request('https://api.resend.com/emails',data=payload,headers={
            'Authorization':f'Bearer {resend_api_key}',
            'Content-Type':'application/json',
        },method='POST')
        try:
            with urllib.request.urlopen(request,timeout=15) as response:
                return 'sent' if 200 <= response.status < 300 else 'failed'
        except Exception:
            return 'failed'
    host=os.environ.get('SMTP_HOST','').strip()
    sender=os.environ.get('SMTP_FROM',os.environ.get('SMTP_USERNAME','')).strip()
    username=os.environ.get('SMTP_USERNAME','').strip()
    password=os.environ.get('SMTP_PASSWORD','')
    if not host or not sender: return 'not_configured'
    if username and not password: return 'missing_credentials'
    message=EmailMessage(); message['Subject']=subject
    message['From']=formataddr((os.environ.get('SMTP_FROM_NAME','BrightCore Recruitment Team'),sender))
    message['To']=recipient; message.set_content(body)
    try:
        port=int(os.environ.get('SMTP_PORT','587'))
        if os.environ.get('SMTP_USE_SSL','').lower() in ('1','true','yes'):
            with smtplib.SMTP_SSL(host,port,timeout=15) as smtp:
                if username: smtp.login(username,password)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(host,port,timeout=15) as smtp:
                smtp.ehlo()
                if os.environ.get('SMTP_STARTTLS','true').lower() in ('1','true','yes'): smtp.starttls(); smtp.ehlo()
                if username: smtp.login(username,password)
                smtp.send_message(message)
        return 'sent'
    except Exception:
        return 'failed'

def initialize():
    if not DATABASE_URL:
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        schema = '''
        CREATE TABLE IF NOT EXISTS admins(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS jobs(id INTEGER PRIMARY KEY, title TEXT NOT NULL, location TEXT NOT NULL, employment_type TEXT NOT NULL, closing_date TEXT NOT NULL, summary TEXT NOT NULL, description TEXT NOT NULL, responsibilities TEXT NOT NULL, requirements TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Open');
        CREATE TABLE IF NOT EXISTS applications(id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL REFERENCES jobs(id), full_name TEXT NOT NULL, email TEXT NOT NULL, phone TEXT NOT NULL, cover_note TEXT NOT NULL, cv_filename TEXT NOT NULL, cv_path TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Pending', note TEXT NOT NULL DEFAULT '', rejection_message TEXT NOT NULL DEFAULT '', acceptance_message TEXT NOT NULL DEFAULT '', notified_status TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(job_id,email));
        '''
        if DATABASE_URL:
            schema = schema.replace('id INTEGER PRIMARY KEY', 'id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY')
            schema = schema.replace('job_id INTEGER NOT NULL REFERENCES jobs(id)', 'job_id BIGINT NOT NULL REFERENCES jobs(id)')
            schema = schema.replace('closing_date TEXT NOT NULL', 'closing_date DATE NOT NULL')
            schema = schema.replace('created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP', 'created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP')
            for statement in schema.split(';'):
                if statement.strip(): db.execute(statement)
            db.execute('CREATE TABLE IF NOT EXISTS admin_sessions(token_hash TEXT PRIMARY KEY, expires_at TIMESTAMPTZ NOT NULL)')
            db.execute('SELECT pg_advisory_xact_lock(712834920)')
            for column in ('rejection_message', 'acceptance_message', 'notified_status'):
                db.execute(f"ALTER TABLE applications ADD COLUMN IF NOT EXISTS {column} TEXT NOT NULL DEFAULT ''")
        else:
            db.executescript(schema)
            cols={row['name'] for row in db.execute('PRAGMA table_info(applications)')}
            if 'rejection_message' not in cols: db.execute("ALTER TABLE applications ADD COLUMN rejection_message TEXT NOT NULL DEFAULT ''")
            if 'acceptance_message' not in cols: db.execute("ALTER TABLE applications ADD COLUMN acceptance_message TEXT NOT NULL DEFAULT ''")
            if 'notified_status' not in cols: db.execute("ALTER TABLE applications ADD COLUMN notified_status TEXT NOT NULL DEFAULT ''")
        if not db.execute('SELECT id FROM admins LIMIT 1').fetchone():
            db.execute('INSERT INTO admins(username,password_hash) VALUES(?,?)', ('admin',hash_password(os.environ.get('ADMIN_PASSWORD','BrightCore2026!'))))
        if not db.execute('SELECT id FROM jobs LIMIT 1').fetchone():
            samples=[('Senior Product Designer','Nairobi, Kenya','Full-time','2027-01-31','Shape thoughtful experiences for millions of customers.','Own product design from discovery to delivery. Partner closely with product and engineering to make financial tools feel effortless.','Lead research and turn insights into clear, accessible journeys.\nBuild and maintain our design system.\nPrototype, test and iterate with customers.','5+ years in product design.\nA portfolio showing strong interaction design.\nClear communication and collaborative instincts.'),('Backend Engineer','Remote · East Africa','Full-time','2027-02-15','Build resilient services for the next generation of banking.','Join our platform team to build secure, scalable services that power every BrightCore product.','Design well-tested APIs and services.\nImprove reliability and observability.\nCollaborate on architecture and technical direction.','3+ years building backend systems.\nExperience with SQL and API design.\nCare for security and operational quality.'),('People Operations Associate','Nairobi, Kenya','Contract','2027-03-01','Help make BrightCore a place where people do their best work.','Create a welcoming, organised employee experience as we grow our people team.','Support onboarding and employee programmes.\nKeep people processes clear and compliant.\nCoordinate hiring and team events.','2+ years in people operations or coordination.\nStrong organisation and communication.\nThoughtful handling of confidential information.')]
            db.executemany('INSERT INTO jobs(title,location,employment_type,closing_date,summary,description,responsibilities,requirements) VALUES(?,?,?,?,?,?,?,?)',samples)

def send_json(handler, status, data):
    body=json.dumps(data,default=str).encode()
    handler.send_response(status); handler.send_header('Content-Type','application/json'); handler.send_header('Content-Length',str(len(body))); handler.send_header('Cache-Control','no-store'); handler.end_headers(); handler.wfile.write(body)

def storage_request(method, path, payload=None, content_type='application/json'):
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError('Supabase storage is not configured.')
    url = SUPABASE_URL + '/storage/v1' + path
    body = json.dumps(payload).encode() if isinstance(payload, dict) else payload
    request = urllib.request.Request(url, data=body, method=method, headers={
        'apikey': SUPABASE_SERVICE_ROLE_KEY,
        'Authorization': 'Bearer ' + SUPABASE_SERVICE_ROLE_KEY,
        'Content-Type': content_type,
    })
    with urllib.request.urlopen(request, timeout=20) as response:
        raw = response.read(MAX_CV + 1)
        if len(raw) > MAX_CV: raise ValueError('Stored CV is larger than 5 MB.')
        return json.loads(raw) if raw else {}

def create_session_cookie(handler, token, max_age):
    secure='; Secure' if os.environ.get('SECURE_COOKIES','').lower() in ('1','true','yes') else ''
    handler.send_header('Set-Cookie',f'session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={max_age}{secure}')

class App(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def session(self):
        jar=SimpleCookie(self.headers.get('Cookie','')); sid=jar['session'].value if 'session' in jar else ''
        if DATABASE_URL:
            try:
                value, signature = sid.rsplit('.', 1)
                expires = int(value)
                secret = os.environ['SESSION_SECRET'].encode()
                expected = hmac.new(secret, value.encode(), hashlib.sha256).hexdigest()
                if expires <= time.time() or not hmac.compare_digest(signature, expected): return None
                token_hash=hashlib.sha256(sid.encode()).hexdigest()
                with connect() as db:
                    active=db.execute('SELECT token_hash FROM admin_sessions WHERE token_hash=? AND expires_at>CURRENT_TIMESTAMP',(token_hash,)).fetchone()
                return value if active else None
            except (ValueError, KeyError): return None
        return sid if SESSIONS.get(sid,0)>time.time() else None
    def body(self):
        length=int(self.headers.get('Content-Length','0'))
        if length>MAX_CV+256_000: raise ValueError('Request is too large.')
        raw=self.rfile.read(length)
        if 'multipart/form-data' in self.headers.get('Content-Type',''):
            message=BytesParser(policy=default).parsebytes(b'Content-Type: '+self.headers['Content-Type'].encode()+b'\r\nMIME-Version: 1.0\r\n\r\n'+raw)
            result={}
            for part in message.iter_parts():
                name=part.get_param('name',header='content-disposition'); filename=part.get_filename()
                result[name]={'filename':filename,'data':part.get_payload(decode=True)} if filename else part.get_content()
            return result
        return json.loads(raw or b'{}')
    def do_GET(self):
        path=urlparse(self.path).path
        if path=='/healthz': return send_json(self,200,{'ok':True})
        if path=='/api/config': return send_json(self,200,{'remote_storage':bool(DATABASE_URL)})
        if path in ('/app.js','/style.css','/assets/hero-background.jpg'):
            file=ROOT/path.lstrip('/'); body=file.read_bytes(); mime={'/app.js':'application/javascript; charset=utf-8','/style.css':'text/css; charset=utf-8','/assets/hero-background.jpg':'image/jpeg'}[path]; self.send_response(200); self.send_header('Content-Type',mime); self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body); return
        if path.startswith('/api/admin') and not self.session(): return send_json(self,401,{'error':'Please sign in to continue.'})
        if path=='/api/jobs':
            with connect() as db: jobs=db.execute("SELECT * FROM jobs WHERE status='Open' AND closing_date>="+('CURRENT_DATE' if DATABASE_URL else "date('now')")+" ORDER BY closing_date").fetchall()
            return send_json(self,200,[dict(x) for x in jobs])
        if path.startswith('/api/jobs/'):
            try: jid=int(path.split('/')[-1])
            except ValueError: return send_json(self,404,{'error':'Job not found.'})
            with connect() as db: job=db.execute("SELECT * FROM jobs WHERE id=? AND status='Open' AND closing_date>="+('CURRENT_DATE' if DATABASE_URL else "date('now')"),(jid,)).fetchone()
            return send_json(self,200,dict(job)) if job else send_json(self,404,{'error':'This job is no longer accepting applications.'})
        if path=='/api/admin/me': return send_json(self,200,{'username':'admin'})
        if path=='/api/admin/overview':
            with connect() as db: rows=db.execute("SELECT j.id,j.title,j.status AS job_status,COUNT(a.id) AS total,SUM(CASE WHEN a.status='Pending' THEN 1 ELSE 0 END) AS pending,SUM(CASE WHEN a.status='Accepted' THEN 1 ELSE 0 END) AS accepted,SUM(CASE WHEN a.status='Rejected' THEN 1 ELSE 0 END) AS rejected FROM jobs j LEFT JOIN applications a ON a.job_id=j.id GROUP BY j.id ORDER BY j.id DESC").fetchall()
            return send_json(self,200,[dict(x) for x in rows])
        if path=='/api/admin/jobs':
            with connect() as db: rows=db.execute('SELECT * FROM jobs ORDER BY id DESC').fetchall()
            return send_json(self,200,[dict(x) for x in rows])
        if path=='/api/admin/applications':
            q=parse_qs(urlparse(self.path).query); status=q.get('status',[''])[0]; job_id=q.get('job_id',[''])[0]
            sql='SELECT a.id,a.job_id,a.full_name,a.email,a.phone,a.cover_note,a.cv_filename,a.status,a.note,a.created_at,j.title FROM applications a JOIN jobs j ON j.id=a.job_id WHERE 1=1'; args=[]
            if status in ('Pending','Accepted','Rejected'): sql+=' AND a.status=?'; args.append(status)
            if job_id.isdigit(): sql+=' AND a.job_id=?'; args.append(int(job_id))
            with connect() as db: rows=db.execute(sql.replace('a.cover_note,a.cv_filename','a.cover_note,a.rejection_message,a.acceptance_message,a.cv_filename,a.notified_status')+' ORDER BY a.created_at DESC',args).fetchall()
            return send_json(self,200,[dict(x) for x in rows])
        match=re.fullmatch(r'/api/admin/applications/(\d+)/cv',path)
        if match:
            with connect() as db: row=db.execute('SELECT cv_path,cv_filename FROM applications WHERE id=?',(int(match[1]),)).fetchone()
            if row and DATABASE_URL:
                try:
                    view = parse_qs(urlparse(self.path).query).get('view')==['1']
                    signed = storage_request('POST', '/object/sign/'+urllib.parse.quote(SUPABASE_CV_BUCKET, safe='')+'/'+urllib.parse.quote(row['cv_path'], safe='/'), {'expiresIn': 120})
                    result = signed.get('signedURL') or signed.get('signedUrl')
                    if not result: raise RuntimeError('Could not create a private CV link.')
                    if result.startswith('/'): result = SUPABASE_URL + '/storage/v1' + result
                    if not view: result += ('&' if '?' in result else '?') + 'download=' + urllib.parse.quote(Path(row['cv_filename']).name)
                    return send_json(self,200,{'url':result})
                except Exception: return send_json(self,500,{'error':'Could not create a private CV link.'})
            if not row or not Path(row['cv_path']).is_file(): return send_json(self,404,{'error':'CV not found.'})
            payload=Path(row['cv_path']).read_bytes(); disposition='inline' if parse_qs(urlparse(self.path).query).get('view')==['1'] else 'attachment'; self.send_response(200); self.send_header('Content-Type','application/pdf'); self.send_header('Content-Disposition',f'{disposition}; filename="{Path(row["cv_filename"]).name}"'); self.send_header('X-Content-Type-Options','nosniff'); self.send_header('Content-Length',str(len(payload))); self.end_headers(); self.wfile.write(payload); return
        if path.startswith('/api/'): return send_json(self,404,{'error':'Not found.'})
        file=ROOT/'index.html'; body=file.read_bytes(); self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_POST(self):
        path=urlparse(self.path).path
        if path == '/api/cv-upload' and DATABASE_URL:
            try:
                data=self.body()
                filename=Path(str(data.get('filename',''))).name
                if not filename.lower().endswith('.pdf') or int(data.get('size',0)) < 5 or int(data.get('size',0)) > MAX_CV:
                    return send_json(self,400,{'error':'Upload a PDF CV no larger than 5 MB.'})
                object_path=secrets.token_hex(24)+'.pdf'
                signed=storage_request('POST','/object/upload/sign/'+urllib.parse.quote(SUPABASE_CV_BUCKET, safe='')+'/'+object_path,{})
                url=signed.get('url') or signed.get('signedURL') or signed.get('signedUrl')
                token=signed.get('token')
                if url and url.startswith('/'): url=SUPABASE_URL+'/storage/v1'+url
                if url and token and 'token=' not in url: url += ('&' if '?' in url else '?')+'token='+urllib.parse.quote(token)
                if not url: raise RuntimeError('Could not create a signed upload URL.')
                return send_json(self,200,{'url':url,'path':object_path})
            except Exception: return send_json(self,500,{'error':'CV upload storage is unavailable. Check the Supabase settings.'})
        try: data=self.body()
        except Exception as e: return send_json(self,400,{'error':str(e) or 'Invalid request.'})
        if path=='/api/login':
            with connect() as db: row=db.execute('SELECT * FROM admins WHERE username=?',(str(data.get('username','')),)).fetchone()
            if not row or not password_matches(str(data.get('password','')),row['password_hash']): return send_json(self,401,{'error':'Email or password is incorrect.'})
            sid=secrets.token_urlsafe(32); max_age=8*3600
            if DATABASE_URL:
                value=str(int(time.time()+max_age)); signature=hmac.new(os.environ.get('SESSION_SECRET','').encode(),value.encode(),hashlib.sha256).hexdigest(); sid=value+'.'+signature
                with connect() as db:
                    db.execute('DELETE FROM admin_sessions WHERE expires_at<=CURRENT_TIMESTAMP')
                    db.execute('INSERT INTO admin_sessions(token_hash,expires_at) VALUES(?,to_timestamp(?))',(hashlib.sha256(sid.encode()).hexdigest(),int(value)))
            else: SESSIONS[sid]=time.time()+max_age
            body=json.dumps({'ok':True}).encode(); self.send_response(200); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(body))); create_session_cookie(self,sid,max_age); self.end_headers(); self.wfile.write(body); return
        if path=='/api/logout':
            jar=SimpleCookie(self.headers.get('Cookie','')); raw_sid=jar['session'].value if 'session' in jar else ''
            sid=self.session()
            if sid and not DATABASE_URL: SESSIONS.pop(raw_sid,None)
            if sid and DATABASE_URL:
                with connect() as db: db.execute('DELETE FROM admin_sessions WHERE token_hash=?',(hashlib.sha256(raw_sid.encode()).hexdigest(),))
            body=json.dumps({'ok':True}).encode(); self.send_response(200); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(body))); create_session_cookie(self,'',0); self.end_headers(); self.wfile.write(body); return
        if path=='/api/applications':
            try:
                jid=int(data.get('job_id',0)); name=str(data.get('full_name','')).strip(); email=str(data.get('email','')).strip().lower(); phone=str(data.get('phone','')).strip(); note=str(data.get('cover_note','')).strip(); cv=data.get('cv')
                if len(name)<2 or len(name)>120: raise ValueError('Enter your full name (2–120 characters).')
                if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email) or len(email)>254: raise ValueError('Enter a valid email address.')
                if len(phone)<7 or len(phone)>30: raise ValueError('Enter a valid phone number.')
                if len(note)>2000: raise ValueError('Your cover note must be under 2,000 characters.')
                if DATABASE_URL:
                    cv_filename=Path(str(data.get('cv_filename',''))).name; cv_path=str(data.get('cv_path',''))
                    if not cv_filename.lower().endswith('.pdf') or not re.fullmatch(r'[a-f0-9]{48}\.pdf',cv_path): raise ValueError('Upload a valid PDF CV.')
                    try:
                        payload=storage_request('GET','/object/authenticated/'+urllib.parse.quote(SUPABASE_CV_BUCKET, safe='')+'/'+cv_path)
                    except Exception: raise ValueError('Could not verify your uploaded CV. Please upload it again.')
                    if not payload.startswith(b'%PDF-'): raise ValueError('Upload a valid PDF CV.')
                    if len(payload)>MAX_CV: raise ValueError('Your CV must be no larger than 5 MB.')
                else:
                    if not isinstance(cv,dict) or not cv.get('filename') or not cv['filename'].lower().endswith('.pdf') or not cv['data'].startswith(b'%PDF-'): raise ValueError('Upload a valid PDF CV.')
                    if len(cv['data'])>MAX_CV: raise ValueError('Your CV must be no larger than 5 MB.')
                    cv_filename=Path(cv['filename']).name
                with connect() as db:
                    job=db.execute("SELECT id FROM jobs WHERE id=? AND status='Open' AND closing_date>="+('CURRENT_DATE' if DATABASE_URL else "date('now')"),(jid,)).fetchone()
                    if not job: return send_json(self,400,{'error':'This job is no longer accepting applications.'})
                    if db.execute('SELECT id FROM applications WHERE job_id=? AND email=?',(jid,email)).fetchone(): return send_json(self,409,{'error':'You have already applied for this job with that email address.'})
                    if not DATABASE_URL:
                        stored=secrets.token_hex(20)+'.pdf'; target=UPLOAD_DIR/stored; target.write_bytes(cv['data']); cv_path=str(target.resolve())
                    try: db.execute('INSERT INTO applications(job_id,full_name,email,phone,cover_note,cv_filename,cv_path) VALUES(?,?,?,?,?,?,?)',(jid,name,email,phone,note,cv_filename,cv_path if DATABASE_URL else cv_path))
                    except Exception:
                        if not DATABASE_URL: target.unlink(missing_ok=True)
                        raise
                return send_json(self,201,{'message':'Your application has been sent. We’ll be in touch soon.'})
            except ValueError as e: return send_json(self,400,{'error':str(e)})
            except Exception: return send_json(self,500,{'error':'Something went wrong while submitting your application.'})
        if path.startswith('/api/admin') and not self.session(): return send_json(self,401,{'error':'Please sign in to continue.'})
        if path=='/api/admin/jobs':
            fields=['title','location','employment_type','closing_date','summary','description','responsibilities','requirements']; vals=[str(data.get(x,'')).strip() for x in fields]
            if any(not v for v in vals): return send_json(self,400,{'error':'Please complete every required job field.'})
            if len(vals[0])>150 or len(vals[4])>300: return send_json(self,400,{'error':'The job title or summary is too long.'})
            with connect() as db: db.execute('INSERT INTO jobs(title,location,employment_type,closing_date,summary,description,responsibilities,requirements) VALUES(?,?,?,?,?,?,?,?)',vals)
            return send_json(self,201,{'ok':True})
        return send_json(self,404,{'error':'Not found.'})
    def do_PATCH(self):
        if not self.path.startswith('/api/admin') or not self.session(): return send_json(self,401,{'error':'Please sign in to continue.'})
        try: data=self.body()
        except Exception: return send_json(self,400,{'error':'Invalid request.'})
        match=re.fullmatch(r'/api/admin/(jobs|applications)/(\d+)',urlparse(self.path).path)
        if not match: return send_json(self,404,{'error':'Not found.'})
        kind,ident=match[1],int(match[2])
        if kind=='jobs':
            fields=['title','location','employment_type','closing_date','summary','description','responsibilities','requirements']; vals=[str(data.get(x,'')).strip() for x in fields]
            if any(not v for v in vals): return send_json(self,400,{'error':'Please complete every required job field.'})
            with connect() as db: cur=db.execute('UPDATE jobs SET title=?,location=?,employment_type=?,closing_date=?,summary=?,description=?,responsibilities=?,requirements=? WHERE id=?',vals+[ident])
            return send_json(self,200,{'ok':True}) if cur.rowcount else send_json(self,404,{'error':'Job not found.'})
        status=data.get('status'); note=str(data.get('note','')).strip(); rejection_message=str(data.get('rejection_message','')).strip(); acceptance_message=str(data.get('acceptance_message','')).strip()
        if status not in ('Pending','Accepted','Rejected') or len(note)>1000 or len(rejection_message)>2000 or len(acceptance_message)>2000: return send_json(self,400,{'error':'Choose a valid status and keep notes and messages within their length limits.'})
        with connect() as db:
            row=db.execute('SELECT a.email,a.full_name,a.status AS previous_status,a.notified_status,j.title FROM applications a JOIN jobs j ON j.id=a.job_id WHERE a.id=?',(ident,)).fetchone()
            if not row: return send_json(self,404,{'error':'Application not found.'})
            db.execute('UPDATE applications SET status=?,note=?,rejection_message=?,acceptance_message=?,notified_status=CASE WHEN status<>? THEN \'\' ELSE notified_status END WHERE id=?',(status,note,rejection_message,acceptance_message,status,ident))
        email_result='already_sent' if status in ('Accepted','Rejected') and row['notified_status']==status else 'not_applicable'
        if status in ('Accepted','Rejected') and row['notified_status']!=status:
            body=acceptance_message if status=='Accepted' else rejection_message
            signature='Kind regards,\n\nBrightCore Recruitment Team\nNorrsken House Kigali\nKG 7 Avenue, Kigali, Rwanda\nPhone: +250 795 677 819\nWebsite: https://www.brightcoretechs.com/'
            if not body and status=='Accepted': body=f"Dear {row['full_name']},\n\nWe are pleased to inform you that you have been shortlisted for an interview for the {row['title']} position at BrightCore Technology Services.\n\nFollowing a review of your application, we would like to invite you to discuss your experience, technical skills, and suitability for the role.\n\nPlease reply to this message to confirm your interest. We will then share the interview date, time, and location with you.\n\nThank you for your interest in joining BrightCore Technology Services. We look forward to speaking with you.\n\n{signature}"
            if not body and status=='Rejected': body=f"Dear {row['full_name']},\n\nThank you for applying for the {row['title']} position at BrightCore Technology Services. We appreciate the time and care you put into your application.\n\nAfter careful consideration, we have decided to move forward with other candidates for this position. We wish you every success in your job search.\n\n{signature}"
            email_result=send_applicant_email(row['email'],f"BrightCore application update: {row['title']}",body)
            if email_result=='sent':
                with connect() as db: db.execute('UPDATE applications SET notified_status=? WHERE id=?',(status,ident))
        return send_json(self,200,{'ok':True,'email':email_result})
    def do_DELETE(self):
        if not self.path.startswith('/api/admin') or not self.session(): return send_json(self,401,{'error':'Please sign in to continue.'})
        match=re.fullmatch(r'/api/admin/jobs/(\d+)',urlparse(self.path).path)
        if not match: return send_json(self,404,{'error':'Not found.'})
        with connect() as db: cur=db.execute("UPDATE jobs SET status='Closed' WHERE id=?",(int(match[1]),))
        return send_json(self,200,{'ok':True}) if cur.rowcount else send_json(self,404,{'error':'Job not found.'})

if __name__=='__main__':
    if DATABASE_URL:
        if len(os.environ.get('SESSION_SECRET','')) < 32:
            raise SystemExit('SESSION_SECRET must contain at least 32 characters when DATABASE_URL is configured.')
        if len(os.environ.get('ADMIN_PASSWORD','')) < 12 or os.environ.get('ADMIN_PASSWORD') == 'BrightCore2026!':
            raise SystemExit('Set a unique ADMIN_PASSWORD with at least 12 characters for the Vercel deployment.')
        if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
            raise SystemExit('Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY for the Vercel deployment.')
    initialize(); port=int(os.environ.get('PORT',8000)); print(f'BrightCore running at http://localhost:{port}'); ThreadingHTTPServer(('0.0.0.0',port),App).serve_forever()
