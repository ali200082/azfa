import copy
import json
import unittest
from unittest.mock import patch

import app as web


class FirebaseResponse:
    status_code = 200
    ok = True

    def __init__(self, value):
        self.value = copy.deepcopy(value)

    def json(self):
        return copy.deepcopy(self.value)


class FirebaseStub:
    def __init__(self):
        self.data = {
            "schools": {
                "S1": {
                    "school_name": "مدرسة الاختبار",
                    "students": {
                        "student-1": {
                            "الكود": "1001",
                            "الاسم": "طالب تجريبي",
                            "المستوى": "اول",
                            "الكروب": "A",
                        }
                    },
                    "users_info": {
                        "teacher1": {"role": "teacher"},
                        "admin1": {"role": "admin"},
                    },
                    "courses": {},
                    "enrollments": {},
                    "course_settings": {},
                }
            }
        }

    def request(self, method, path, **kwargs):
        parts = path.split("/")
        parent = self.data
        for part in parts[:-1]:
            parent = parent.setdefault(part, {}) if method != "GET" else parent.get(part, {})
            if not isinstance(parent, dict):
                return FirebaseResponse(None)
        key = parts[-1]
        if method == "GET":
            return FirebaseResponse(parent.get(key))
        if method == "PUT":
            parent[key] = copy.deepcopy(kwargs.get("json"))
        elif method == "PATCH":
            current = parent.setdefault(key, {})
            if isinstance(current, dict):
                current.update(copy.deepcopy(kwargs.get("json") or {}))
            else:
                parent[key] = copy.deepcopy(kwargs.get("json"))
        elif method == "DELETE":
            parent.pop(key, None)
        return FirebaseResponse(parent.get(key))


class CourseWebTests(unittest.TestCase):
    def setUp(self):
        web.app.config.update(TESTING=True, SECRET_KEY="test-secret")
        self.client = web.app.test_client()
        self.firebase = FirebaseStub()
        self.firebase_patch = patch.object(
            web, "_fb_request", side_effect=self.firebase.request
        )
        self.firebase_patch.start()
        self.addCleanup(self.firebase_patch.stop)
        with self.client.session_transaction() as current_session:
            current_session["username"] = "admin1"
            current_session["role"] = "admin"
            current_session["school_id"] = "S1"
            current_session["is_developer"] = False

    def _start_logged_out(self):
        with self.client.session_transaction() as current_session:
            current_session.clear()

    def test_login_selects_school_first_and_uses_admin_role_without_school_picker(self):
        school = self.firebase.data["schools"]["S1"]
        school["users_info"]["admin1"]["pwd_hash"] = web._sha256("secret")
        self._start_logged_out()

        response = self.client.get("/login")
        self.assertEqual(response.status_code, 200)
        self.assertIn("اسم المدرسة أو رمزها".encode(), response.data)
        self.assertNotIn(b'id="username"', response.data)

        response = self.client.post(
            "/login", data={"action": "select_school", "school": "مدرسة الاختبار"}
        )
        self.assertEqual(response.status_code, 302)
        response = self.client.get("/login")
        self.assertIn("مدرسة الاختبار".encode(), response.data)
        self.assertIn(b'id="username"', response.data)

        response = self.client.post(
            "/login",
            data={
                "action": "authenticate",
                "username": "admin1",
                "password": "secret",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/")
        with self.client.session_transaction() as current_session:
            self.assertEqual(current_session["username"], "admin1")
            self.assertEqual(current_session["role"], "admin")
            self.assertEqual(current_session["school_id"], "S1")

        response = self.client.get("/schools")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/")

    def test_login_authenticates_reused_username_only_in_typed_school(self):
        second_school = copy.deepcopy(self.firebase.data["schools"]["S1"])
        second_school["school_name"] = "مدرسة ثانية"
        second_school["users_info"]["teacher1"] = {
            "role": "teacher",
            "pwd_hash": web._sha256("second-secret"),
            "assigned_level": "ثاني",
            "assigned_groups": ["B"],
        }
        self.firebase.data["schools"]["S2"] = second_school
        self.firebase.data["schools"]["S1"]["users_info"]["teacher1"]["pwd_hash"] = (
            web._sha256("first-secret")
        )
        self._start_logged_out()

        self.client.post(
            "/login", data={"action": "select_school", "school": "مدرسة الاختبار"}
        )
        response = self.client.post(
            "/login",
            data={
                "action": "authenticate",
                "username": "teacher1",
                "password": "second-secret",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("اسم المستخدم أو كلمة المرور غير صحيحة".encode(), response.data)

        self.client.post(
            "/login", data={"action": "change_school"}
        )
        self.client.post(
            "/login", data={"action": "select_school", "school": "S2"}
        )
        response = self.client.post(
            "/login",
            data={
                "action": "authenticate",
                "username": "teacher1",
                "password": "second-secret",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as current_session:
            self.assertEqual(current_session["role"], "teacher")
            self.assertEqual(current_session["school_id"], "S2")
            self.assertEqual(current_session["assigned_level"], "ثاني")
            self.assertEqual(current_session["assigned_groups"], ["B"])

    def test_duplicate_school_names_require_school_id(self):
        duplicate_school = copy.deepcopy(self.firebase.data["schools"]["S1"])
        self.firebase.data["schools"]["S2"] = duplicate_school
        self._start_logged_out()

        response = self.client.post(
            "/login", data={"action": "select_school", "school": "مدرسة الاختبار"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("اكتب رمز المدرسة بدل الاسم".encode(), response.data)
        with self.client.session_transaction() as current_session:
            self.assertNotIn("login_school_id", current_session)

    def test_developer_username_in_school_step_opens_global_developer_login(self):
        self._start_logged_out()

        with patch.object(
            web, "_fb_request", side_effect=AssertionError("Firebase must not be queried")
        ):
            response = self.client.post(
                "/login",
                data={"action": "select_school", "school": web.DEVELOPER_ID},
            )
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as current_session:
            self.assertTrue(current_session["login_developer_mode"])
            self.assertNotIn("login_school_id", current_session)

        response = self.client.get("/login")
        self.assertEqual(response.status_code, 200)
        self.assertIn("الوصول إلى جميع المدارس".encode(), response.data)
        self.assertIn(
            f'value="{web.DEVELOPER_ID}"'.encode(), response.data)

        with patch.object(web, "DEVELOPER_HASH", web._sha256("developer-secret")):
            response = self.client.post(
                "/login",
                data={
                    "action": "authenticate",
                    "username": web.DEVELOPER_ID,
                    "password": "developer-secret",
                },
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/schools")
        with self.client.session_transaction() as current_session:
            self.assertTrue(current_session["is_developer"])
            self.assertEqual(current_session["role"], "admin")
            self.assertNotIn("school_id", current_session)

        response = self.client.get("/schools")
        self.assertEqual(response.status_code, 200)

    def test_developer_mode_rejects_invalid_developer_credentials(self):
        self._start_logged_out()
        self.client.post(
            "/login",
            data={"action": "select_school", "school": web.DEVELOPER_ID_LEGACY},
        )

        response = self.client.post(
            "/login",
            data={
                "action": "authenticate",
                "username": web.DEVELOPER_ID_LEGACY,
                "password": "wrong-password",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("بيانات حساب المطور غير صحيحة".encode(), response.data)
        with self.client.session_transaction() as current_session:
            self.assertNotIn("username", current_session)

    def test_course_creation_enrollment_attendance_and_grades_use_shared_paths(self):
        response = self.client.post(
            "/courses",
            data={"action": "add_course", "gregorian_year": "2026"},
        )
        self.assertEqual(response.status_code, 302)
        school = self.firebase.data["schools"]["S1"]
        course_id, course = next(iter(school["courses"].items()))
        self.assertEqual(course["course_id"], course_id)
        self.assertEqual(course["sequence"], 1)
        self.assertEqual(school["course_settings"]["sequence_counters"]["2026"], 2)

        response = self.client.post(
            "/courses",
            data={
                "action": "enroll_student",
                "course_id": course_id,
                "student_id": "student-1",
                "teacher": "teacher1",
            },
        )
        self.assertEqual(response.status_code, 302)
        enrollment_id, enrollment = next(iter(school["enrollments"].items()))
        self.assertEqual(enrollment["course_id"], course_id)
        self.assertEqual(enrollment["student_code"], "1001")
        self.assertEqual(enrollment["teacher"], "teacher1")

        response = self.client.get(f"/courses?course={course_id}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("طالب تجريبي".encode(), response.data)
        response = self.client.post(f"/courses/select/{course_id}")
        self.assertEqual(response.status_code, 302)
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("لوحة المتابعة".encode(), response.data)
        response = self.client.post(
            "/attendance",
            data={"action": "absent", "students": enrollment_id},
        )
        self.assertEqual(response.status_code, 200)
        enrollment = school["enrollments"][enrollment_id]
        self.assertEqual(enrollment["attendance"][0]["الحالة"], "غائب")
        self.assertEqual(enrollment["grades"]["غياب"], 1)
        self.assertEqual(enrollment["grades"]["درجة الحضور"], 20)

        response = self.client.post(
            "/grades?code=1001",
            data={"النشاط": "8", "الشفهي": "15", "التحريري": "50"},
        )
        self.assertEqual(response.status_code, 302)
        enrollment = school["enrollments"][enrollment_id]
        self.assertEqual(enrollment["grades"]["النشاط"], 8)
        self.assertEqual(enrollment["grades"]["الشفهي"], 15)
        self.assertNotIn("النشاط", school["students"]["student-1"])

        response = self.client.get("/grades?code=1001")
        self.assertEqual(response.status_code, 200)
        response = self.client.get("/reports")
        self.assertEqual(response.status_code, 200)
        response = self.client.get("/reports/statistics")
        self.assertEqual(response.status_code, 200)
        self.assertIn("طالب تجريبي".encode(), response.data)

    def test_teacher_cannot_manage_courses_or_select_unassigned_course(self):
        school = self.firebase.data["schools"]["S1"]
        school["courses"]["assigned"] = {
            "course_id": "assigned",
            "gregorian_year": 2026,
            "sequence": 1,
            "teacher_usernames": ["teacher1"],
            "archived": False,
        }
        school["courses"]["private"] = {
            "course_id": "private",
            "gregorian_year": 2026,
            "sequence": 2,
            "teacher_usernames": ["another_teacher"],
            "archived": False,
        }
        with self.client.session_transaction() as current_session:
            current_session["username"] = "teacher1"
            current_session["role"] = "teacher"
        response = self.client.post(
            "/courses", data={"action": "add_course", "gregorian_year": "2026"}
        )
        self.assertEqual(response.status_code, 403)
        response = self.client.post("/courses/select/private")
        self.assertEqual(response.status_code, 403)
        response = self.client.post("/courses/select/assigned")
        self.assertEqual(response.status_code, 302)

    def test_enrollment_can_be_edited_without_losing_course_records(self):
        self.client.post(
            "/courses",
            data={"action": "add_course", "gregorian_year": "2026"},
        )
        school = self.firebase.data["schools"]["S1"]
        course_id, _ = next(iter(school["courses"].items()))
        self.client.post(
            "/courses",
            data={
                "action": "enroll_student",
                "course_id": course_id,
                "student_id": "student-1",
                "teacher": "teacher1",
            },
        )
        enrollment_id, enrollment = next(iter(school["enrollments"].items()))
        enrollment["grades"] = {"النشاط": 7}
        enrollment["attendance"] = [{"التاريخ": "2026-01-01", "الحالة": "حاضر"}]

        response = self.client.post(
            "/courses",
            data={
                "action": "edit_enrollment",
                "course_id": course_id,
                "enrollment_id": enrollment_id,
                "level": "ثاني",
                "group": "B",
                "teacher": "",
            },
        )

        self.assertEqual(response.status_code, 302)
        updated = school["enrollments"][enrollment_id]
        self.assertEqual(updated["level"], "ثاني")
        self.assertEqual(updated["group"], "B")
        self.assertEqual(updated["teacher"], "")
        self.assertEqual(updated["grades"], {"النشاط": 7})
        self.assertEqual(updated["attendance"], [{"التاريخ": "2026-01-01", "الحالة": "حاضر"}])

    def test_backup_contains_school_data_without_credentials(self):
        response = self.client.get("/backup")
        self.assertEqual(response.status_code, 200)
        snapshot = json.loads(response.get_data(as_text=True))
        self.assertEqual(snapshot["format"], "azfa-web-backup-v1")
        self.assertIn("student-1", snapshot["students"])
        self.assertNotIn("users_info", snapshot)
