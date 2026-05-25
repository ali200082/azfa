#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
تطبيق ويب لإدارة بيانات الطلاب (AZFA Web)
- يعمل في المتصفح على الموبايل والحاسبة
- يقرأ/يكتب البيانات على نفس Firebase الخاص ببرنامج الحاسبة الحالي
  المسار: schools/<school_id>/students/<student_id>
- لا يعدل أي ملف من البرنامج الأصلي
"""
from flask import (Flask, render_template, request, redirect, url_for,
                   jsonify, flash, session)
import requests
import uuid
import os
from datetime import datetime

# ────────────── إعدادات Firebase (نفس البرنامج الحالي) ──────────────
FIREBASE_URL = "https://azfa-3ff21-default-rtdb.firebaseio.com"
FIREBASE_URL_FALLBACK = "https://falling-haze-c742.ahmed-wazir-hlail.workers.dev"
HTTP_TIMEOUT = 15

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "azfa-web-secret-change-me-in-prod")

# ────────────── حقول الطالب ──────────────
STUDENT_FIELDS = [
    ("الكود", "text"),
    ("الاسم", "text"),
    ("المستوى", "text"),
    ("الكروب", "text"),
    ("غياب", "number"),
    ("درجة الحضور", "number"),
    ("النشاط", "number"),
    ("الشفهي", "number"),
    ("التحريري", "number"),
]
NUMERIC_FIELDS = {"غياب", "درجة الحضور", "النشاط", "الشفهي", "التحريري"}


# ────────────── طبقة Firebase ──────────────
def _fb_request(method, path, **kwargs):
    """طلب HTTP مع fallback تلقائي لرابط Firebase البديل."""
    last_err = None
    for base in (FIREBASE_URL, FIREBASE_URL_FALLBACK):
        if not base:
            continue
        url = f"{base.rstrip('/')}/{path}.json"
        try:
            r = requests.request(method, url, timeout=HTTP_TIMEOUT, **kwargs)
            if r.status_code < 500:
                return r
        except Exception as e:
            last_err = e
            continue
    if last_err:
        raise last_err
    return None


def fb_get(path):
    try:
        r = _fb_request("GET", path)
        return r.json() if r is not None and r.ok else None
    except Exception as e:
        print(f"[Firebase GET error] {path}: {e}")
        return None


def fb_put(path, data):
    try:
        r = _fb_request("PUT", path, json=data)
        return r is not None and r.ok
    except Exception as e:
        print(f"[Firebase PUT error] {path}: {e}")
        return False


def fb_patch(path, data):
    try:
        r = _fb_request("PATCH", path, json=data)
        return r is not None and r.ok
    except Exception as e:
        print(f"[Firebase PATCH error] {path}: {e}")
        return False


def fb_delete(path):
    try:
        r = _fb_request("DELETE", path)
        return r is not None and r.ok
    except Exception as e:
        print(f"[Firebase DELETE error] {path}: {e}")
        return False


# ────────────── طبقة المدارس والطلاب ──────────────
def list_schools():
    """يرجع: [{id, name, count}, ...]"""
    data = fb_get("schools")
    if not isinstance(data, dict):
        return []
    schools = []
    for sid, info in data.items():
        if not isinstance(info, dict):
            continue
        schools.append({
            "id": sid,
            "name": info.get("school_name", sid),
            "count": info.get("students_count", 0),
        })
    return sorted(schools, key=lambda x: str(x["name"]))


def current_school_id():
    """يرجع معرف المدرسة المختار حالياً (من query ثم session)."""
    sid = request.args.get("school") or session.get("school_id")
    if sid and request.args.get("school"):
        session["school_id"] = sid
    return sid


def students_path(school_id, student_id=None):
    if student_id:
        return f"schools/{school_id}/students/{student_id}"
    return f"schools/{school_id}/students"


def load_students(school_id):
    data = fb_get(students_path(school_id))
    if not data:
        return []
    students = []
    if isinstance(data, dict):
        for sid, s in data.items():
            if isinstance(s, dict):
                s = dict(s)
                s["id"] = sid
                students.append(s)
    elif isinstance(data, list):
        for i, s in enumerate(data):
            if isinstance(s, dict):
                s = dict(s)
                s.setdefault("id", str(i))
                students.append(s)
    return students


def get_student(school_id, sid):
    data = fb_get(students_path(school_id, sid))
    if isinstance(data, dict):
        data["id"] = sid
        return data
    return None


def _update_school_meta(school_id):
    """يحدث students_count و last_updated مثل البرنامج الأصلي."""
    students = fb_get(students_path(school_id))
    count = len(students) if isinstance(students, (dict, list)) else 0
    fb_patch(f"schools/{school_id}", {
        "students_count": count,
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "updated_by": "AZFA Web",
    })


def save_student(school_id, sid, payload):
    ok = fb_put(students_path(school_id, sid), payload)
    if ok:
        _update_school_meta(school_id)
    return ok


def remove_student_db(school_id, sid):
    ok = fb_delete(students_path(school_id, sid))
    if ok:
        _update_school_meta(school_id)
    return ok


def _parse_form(form):
    out = {}
    for name, _ in STUDENT_FIELDS:
        v = form.get(name, "").strip()
        if name in NUMERIC_FIELDS:
            try:
                val = float(v) if v else 0
                out[name] = int(val) if val == int(val) else val
            except ValueError:
                out[name] = 0
        else:
            out[name] = v
    return out


def _calc_total(s):
    try:
        return sum(float(s.get(f, 0) or 0) for f in
                   ("درجة الحضور", "النشاط", "الشفهي", "التحريري"))
    except (TypeError, ValueError):
        return 0


# ────────────── السياق العام للقوالب ──────────────
@app.context_processor
def inject_globals():
    schools = list_schools()
    sid = session.get("school_id")
    current = next((s for s in schools if s["id"] == sid), None)
    return {"all_schools": schools, "current_school": current}


# ────────────── المسارات ──────────────
@app.route("/")
def index():
    school_id = current_school_id()
    if not school_id:
        return redirect(url_for("schools_page"))

    q = request.args.get("q", "").strip()
    level = request.args.get("level", "").strip()
    group = request.args.get("group", "").strip()

    all_students = load_students(school_id)
    students = all_students

    if q:
        ql = q.lower()
        students = [s for s in students
                    if ql in str(s.get("الاسم", "")).lower()
                    or ql in str(s.get("الكود", "")).lower()]
    if level:
        students = [s for s in students if str(s.get("المستوى", "")) == level]
    if group:
        students = [s for s in students if str(s.get("الكروب", "")) == group]

    for s in students:
        s["_total"] = _calc_total(s)

    levels = sorted({str(s.get("المستوى", "")) for s in all_students if s.get("المستوى")})
    groups = sorted({str(s.get("الكروب", "")) for s in all_students if s.get("الكروب")})

    return render_template("index.html",
                           students=students, q=q, level=level, group=group,
                           levels=levels, groups=groups,
                           fields=STUDENT_FIELDS,
                           total_count=len(all_students))


@app.route("/schools")
def schools_page():
    return render_template("schools.html", schools=list_schools())


@app.route("/schools/select/<school_id>")
def select_school(school_id):
    session["school_id"] = school_id
    flash("تم اختيار المدرسة ✓", "success")
    return redirect(url_for("index"))


@app.route("/student/new", methods=["GET", "POST"])
def new_student():
    school_id = current_school_id()
    if not school_id:
        flash("اختر مدرسة أولاً", "error")
        return redirect(url_for("schools_page"))
    if request.method == "POST":
        data = _parse_form(request.form)
        if not data.get("الاسم"):
            flash("الاسم مطلوب", "error")
            return render_template("form.html", student=data, fields=STUDENT_FIELDS, action="إضافة")
        sid = data.get("الكود", "").strip() or str(uuid.uuid4())[:12]
        if get_student(school_id, sid):
            sid = str(uuid.uuid4())[:12]
        if save_student(school_id, sid, data):
            flash("تمت الإضافة بنجاح ✓", "success")
            return redirect(url_for("index"))
        flash("فشل الحفظ — تحقق من الاتصال بالإنترنت", "error")
        return render_template("form.html", student=data, fields=STUDENT_FIELDS, action="إضافة")
    return render_template("form.html", student={}, fields=STUDENT_FIELDS, action="إضافة")


@app.route("/student/<sid>/edit", methods=["GET", "POST"])
def edit_student(sid):
    school_id = current_school_id()
    if not school_id:
        return redirect(url_for("schools_page"))
    student = get_student(school_id, sid)
    if not student:
        flash("الطالب غير موجود", "error")
        return redirect(url_for("index"))
    if request.method == "POST":
        data = _parse_form(request.form)
        if save_student(school_id, sid, data):
            flash("تم التعديل ✓", "success")
            return redirect(url_for("index"))
        flash("فشل الحفظ", "error")
    return render_template("form.html", student=student, fields=STUDENT_FIELDS, action="تعديل")


@app.route("/student/<sid>/delete", methods=["POST"])
def remove_student(sid):
    school_id = current_school_id()
    if not school_id:
        return redirect(url_for("schools_page"))
    if remove_student_db(school_id, sid):
        flash("تم الحذف ✓", "success")
    else:
        flash("فشل الحذف", "error")
    return redirect(url_for("index"))


@app.route("/student/<sid>")
def view_student(sid):
    school_id = current_school_id()
    if not school_id:
        return redirect(url_for("schools_page"))
    student = get_student(school_id, sid)
    if not student:
        flash("الطالب غير موجود", "error")
        return redirect(url_for("index"))
    student["_total"] = _calc_total(student)
    return render_template("view.html", student=student, fields=STUDENT_FIELDS)


@app.route("/api/students")
def api_students():
    school_id = current_school_id()
    if not school_id:
        return jsonify([])
    return jsonify(load_students(school_id))


@app.route("/api/schools")
def api_schools():
    return jsonify(list_schools())


@app.route("/health")
def health():
    schools = list_schools()
    return jsonify({
        "firebase": "ok" if schools else "fail",
        "schools_count": len(schools),
        "time": datetime.now().isoformat(),
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"\n🌐 افتح المتصفح على: http://localhost:{port}")
    print(f"📱 من الموبايل (نفس الواي فاي): http://<IP-الحاسبة>:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=False)
