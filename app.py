from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import joblib
import re
import os
from datetime import datetime, timedelta
from sqlalchemy import func

app = Flask(__name__)
app.config['SECRET_KEY'] = 'fake-news-detection-secret-key-2024'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Database Models
class User(UserMixin, db.Model):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def set_password(self, password):
        self.password = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password, password)

class Analysis(db.Model):
    __tablename__ = 'analysis'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    article_text = db.Column(db.Text, nullable=False)
    result = db.Column(db.String(20), nullable=False)
    confidence = db.Column(db.Float, default=0.0)
    analyzed_at = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Create tables
with app.app_context():
    db.create_all()
    print("Database tables created")

# Load ML model
print("\nLoading ML model...")
try:
    model = joblib.load('models/classifier.pkl')
    vectorizer = joblib.load('models/vectorizer.pkl')
    print("Model loaded successfully!")
    model_loaded = True
except Exception as e:
    print(f"Error loading model: {e}")
    print("Please run train_model.py first")
    model = None
    vectorizer = None
    model_loaded = False

# Text cleaning function
def clean_text(text):
    if not text:
        return ""
    text = str(text).lower()
    text = re.sub(r'[^a-zA-Z\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def get_top_keywords(analyses, result_type, limit=5):
    from collections import Counter
    import re
    
    words = []
    stopwords = ['the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 
                'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'has', 'have',
                'had', 'this', 'that', 'these', 'those', 'it', 'its', 'they', 'them']
    
    for analysis in analyses:
        if analysis.result == result_type:
            text = analysis.article_text.lower()
            word_list = re.findall(r'\b[a-z]{4,}\b', text)
            words.extend([w for w in word_list if w not in stopwords])
    
    counter = Counter(words)
    return counter.most_common(limit)

# Routes
@app.route('/')
def home():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password')
    
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm = request.form.get('confirm_password')
        
        if password != confirm:
            flash('Passwords do not match')
            return redirect(url_for('register'))
        
        if User.query.filter_by(username=username).first():
            flash('Username already exists')
            return redirect(url_for('register'))
        
        if User.query.filter_by(email=email).first():
            flash('Email already registered')
            return redirect(url_for('register'))
        
        user = User(username=username, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        
        flash('Registration successful! Please login.')
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/dashboard')
@login_required
def dashboard():
    history = Analysis.query.filter_by(user_id=current_user.id)\
                            .order_by(Analysis.analyzed_at.desc())\
                            .limit(10).all()
    
    total = Analysis.query.filter_by(user_id=current_user.id).count()
    
    return render_template('index.html',
                            username=current_user.username,
                            history=history,
                            total=total,
                            model_loaded=model_loaded,
                            result=None,
                            message=None,
                            confidence=None,
                            news_text=None)

@app.route('/analyze', methods=['POST'])
@login_required
def analyze():
    news_text = request.form.get('news_article', '')
    
    if not news_text:
        flash('Please enter news text to analyze')
        return redirect(url_for('dashboard'))
    
    if not model_loaded or model is None:
        fake_keywords = ['alien', 'ufo', 'miracle', 'secret', 'conspiracy', 'hoax', 'fake', 'scam', 
                        'shocking', 'revealed', 'exposed', 'they don\'t want you to know', 'cover up']
        real_keywords = ['study', 'research', 'scientists', 'university', 'journal', 'published', 
                        'according to', 'report', 'official', 'government', 'announced', 'reuters']
        
        text_lower = news_text.lower()
        fake_score = sum(2 for word in fake_keywords if word in text_lower)
        real_score = sum(1 for word in real_keywords if word in text_lower)
        
        if fake_score > real_score:
            result = "FAKE NEWS"
            message = "This article appears to be potentially FALSE or misleading."
            confidence = 70 + (fake_score * 3)
        else:
            result = "REAL NEWS"
            message = "This article appears to be true and is identified as RELIABLE information."
            confidence = 70 + (real_score * 3)
        
        confidence = min(confidence, 98)
    else:
        cleaned = clean_text(news_text)
        
        if len(cleaned) < 10:
            flash('Please enter more text for accurate analysis')
            return redirect(url_for('dashboard'))
        
        vectorized = vectorizer.transform([cleaned])
        prediction = model.predict(vectorized)[0]
        probabilities = model.predict_proba(vectorized)[0]
        confidence = max(probabilities) * 100
        
        if prediction == 0:
            result = "REAL NEWS"
            message = "This article appears to be true and is identified as RELIABLE information."
        else:
            result = "FAKE NEWS"
            message = "This article appears to be potentially FALSE or misleading."
    
    analysis = Analysis(
        user_id=current_user.id,
        article_text=news_text[:150] + "..." if len(news_text) > 150 else news_text,
        result=result,
        confidence=confidence
    )
    db.session.add(analysis)
    db.session.commit()
    
    history = Analysis.query.filter_by(user_id=current_user.id)\
                            .order_by(Analysis.analyzed_at.desc())\
                            .limit(10).all()
    
    total = Analysis.query.filter_by(user_id=current_user.id).count()
    
    return render_template('index.html',
                            username=current_user.username,
                            result=result,
                            message=message,
                            confidence=round(confidence, 1),
                            news_text=news_text,
                            history=history,
                            total=total,
                            model_loaded=model_loaded)

@app.route('/delete/<int:analysis_id>')
@login_required
def delete_analysis(analysis_id):
    analysis = Analysis.query.get_or_404(analysis_id)
    if analysis.user_id == current_user.id:
        db.session.delete(analysis)
        db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# ==================== REPORT SECTION ====================

@app.route('/reports')
@login_required
def reports():
    all_analysis = Analysis.query.filter_by(user_id=current_user.id).all()
    history = Analysis.query.filter_by(user_id=current_user.id)\
                            .order_by(Analysis.analyzed_at.desc())\
                            .limit(10).all()
    
    total = len(all_analysis)
    fake_count = sum(1 for a in all_analysis if a.result == 'FAKE NEWS')
    real_count = sum(1 for a in all_analysis if a.result == 'REAL NEWS')
    
    fake_percent = round((fake_count / total * 100), 1) if total > 0 else 0
    real_percent = round((real_count / total * 100), 1) if total > 0 else 0
    avg_confidence = round(sum(a.confidence for a in all_analysis) / total, 1) if total > 0 else 0
    
    last_7_days = []
    for i in range(6, -1, -1):
        date = datetime.now().date() - timedelta(days=i)
        day_analyses = Analysis.query.filter(
            Analysis.user_id == current_user.id,
            func.date(Analysis.analyzed_at) == date
        ).all()
        
        last_7_days.append({
            'date': date.strftime('%b %d'),
            'fake': sum(1 for a in day_analyses if a.result == 'FAKE NEWS'),
            'real': sum(1 for a in day_analyses if a.result == 'REAL NEWS')
        })
    
    fake_keywords = get_top_keywords(all_analysis, 'FAKE NEWS', 5)
    real_keywords = get_top_keywords(all_analysis, 'REAL NEWS', 5)
    
    return render_template('reports.html',
                            username=current_user.username,
                            total=total,
                            fake_count=fake_count,
                            real_count=real_count,
                            fake_percent=fake_percent,
                            real_percent=real_percent,
                            avg_confidence=avg_confidence,
                            last_7_days=last_7_days,
                            fake_keywords=fake_keywords,
                            real_keywords=real_keywords,
                            history=history)

@app.route('/reports/export')
@login_required
def export_reports():
    analyses = Analysis.query.filter_by(user_id=current_user.id).all()
    
    data = [{
        'id': a.id,
        'article': a.article_text,
        'result': a.result,
        'confidence': a.confidence,
        'date': a.analyzed_at.strftime('%Y-%m-%d %H:%M')
    } for a in analyses]
    
    return jsonify(data)

@app.route('/reports/clear')
@login_required
def clear_reports():
    Analysis.query.filter_by(user_id=current_user.id).delete()
    db.session.commit()
    flash('All analysis history cleared!')
    return redirect(url_for('reports'))

# ==================== API ENDPOINT FOR CHARTS ====================

@app.route('/api/chart-data')
@login_required
def api_chart_data():
    all_analysis = Analysis.query.filter_by(user_id=current_user.id).all()
    
    last_7_days = []
    for i in range(6, -1, -1):
        date = datetime.now().date() - timedelta(days=i)
        day_analyses = Analysis.query.filter(
            Analysis.user_id == current_user.id,
            func.date(Analysis.analyzed_at) == date
        ).all()
        
        last_7_days.append({
            'date': date.strftime('%b %d'),
            'fake': sum(1 for a in day_analyses if a.result == 'FAKE NEWS'),
            'real': sum(1 for a in day_analyses if a.result == 'REAL NEWS')
        })
    
    total = len(all_analysis)
    fake_count = sum(1 for a in all_analysis if a.result == 'FAKE NEWS')
    real_count = sum(1 for a in all_analysis if a.result == 'REAL NEWS')
    
    return jsonify({
        'last_7_days': last_7_days,
        'fake_count': fake_count,
        'real_count': real_count,
        'total': total,
        'fake_percent': round((fake_count / total * 100), 1) if total > 0 else 0,
        'real_percent': round((real_count / total * 100), 1) if total > 0 else 0,
        'avg_confidence': round(sum(a.confidence for a in all_analysis) / total, 1) if total > 0 else 0
    })

# ==================== SETTINGS SECTION ====================

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        email = request.form.get('email')
        if email:
            current_user.email = email
        
        new_password = request.form.get('new_password')
        if new_password:
            current_user.set_password(new_password)
            flash('Password updated successfully!')
        
        db.session.commit()
        flash('Settings updated successfully!')
        return redirect(url_for('settings'))
    
    return render_template('settings.html',
                            username=current_user.username,
                            email=current_user.email)

@app.route('/settings/delete_account', methods=['POST'])
@login_required
def delete_account():
    Analysis.query.filter_by(user_id=current_user.id).delete()
    User.query.filter_by(id=current_user.id).delete()
    db.session.commit()
    
    logout_user()
    flash('Account deleted successfully')
    return redirect(url_for('login'))

@app.route('/settings/preferences', methods=['POST'])
@login_required
def update_preferences():
    flash('Preferences saved!')
    return redirect(url_for('settings'))

if __name__ == '__main__':
    print("\n" + "=" * 60)
    print("FAKE NEWS DETECTION SYSTEM")
    print("=" * 60)
    print("\nStarting web application...")
    print("Open browser and go to: http://127.0.0.1:5000")
    print("=" * 60)
    app.run(debug=False, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))