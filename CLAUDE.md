# CLAUDE.md - Project Guide for Claude Code

## Project Overview

**hyojin-system** is a Korean business automation web application built with Flask. It provides tools for e-commerce order processing, employee attendance management, inventory tracking, and various Excel-based data processing utilities.

## Tech Stack

- **Backend**: Flask 3.0, Python 3.11
- **Database**: Supabase (optional, falls back to JSON file mode)
- **Frontend**: Vanilla JavaScript, HTML templates (Jinja2)
- **Data Processing**: Pandas, NumPy, OpenPyXL, xlrd
- **PDF Generation**: WeasyPrint (requires system fonts)
- **Deployment**: Render with Gunicorn

## Project Structure

```
hyojin/
├── app.py                      # Main Flask application (~2600 lines)
├── requirements.txt            # Python dependencies
├── render.yaml                 # Render deployment config
├── playauto_settings_v4.json   # Invoice classification settings
├── margin_data.json            # Product margin data
├── schema_attendance.sql       # Database schema reference
├── fonts/                      # Custom fonts for PDF generation
└── templates/
    ├── index.html              # Main application UI
    ├── login.html              # Login page
    └── parttime.html           # Part-time employee interface
```

## Key Features

### 1. Excel Processing Tools
- **Star Delivery Filter** (`/upload`): Filters out "판매자 스타배송" rows from Excel files
- **Invoice Classification** (`/classify`): Auto-classifies orders by worker/handler based on product rules
- **Tax-Free Processing** (`/api/tax-free/process`): Extracts tax-free data from Coupang sales reports

### 2. Employee & Attendance Management
- Employee CRUD (`/api/employees`)
- Attendance tracking (`/api/attendance`)
- Edit request workflow (`/api/attendance-edit-request`)
- Salary calculation (`/api/salary/calculate`)
- Holiday management (`/api/holidays`)

### 3. Inventory Management
- Product margin tracking (`/api/margin`)
- Out-of-stock tracking (`/api/out-of-stock`)
- Box inventory (`/api/box-inventory`)
- Arrival products (`/api/arrival-products`)
- Invoice generation (`/api/arrival-invoice/generate`)

### 4. Worker/Product Assignment
- Worker management (`/api/workers`)
- Product assignment per worker (`/api/workers/<id>/products`)

## Development Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run locally (development)
python app.py

# Run with Gunicorn (production)
gunicorn app:app

# Server runs on http://localhost:5000
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `SECRET_KEY` | Flask session secret | `playauto-secret-key-2024` |
| `SUPABASE_URL` | Supabase project URL | (empty - uses JSON mode) |
| `SUPABASE_KEY` | Supabase API key | (empty - uses JSON mode) |
| `LOGIN_ID` | User login ID | `abc` |
| `LOGIN_PW` | User login password | `1234` |
| `ADMIN_ID` | Admin login ID | Same as LOGIN_ID |
| `ADMIN_PW` | Admin login password | Same as LOGIN_PW |

## Authentication

- Two roles: `user` and `admin`
- Login required for most routes (uses `@login_required` decorator)
- Admin routes use `@admin_required` decorator
- Session-based authentication

## Database Modes

The app supports two data storage modes:
1. **Supabase Mode**: When `SUPABASE_URL` and `SUPABASE_KEY` are set
2. **JSON File Mode**: Falls back to local JSON files when Supabase is unavailable

## Key Code Patterns

### Time Handling
- Uses KST (Korea Standard Time, UTC+9)
- Helper function: `get_kst_today()` returns current date in KST

### File Upload
- Max file size: 16MB
- Allowed extensions: `.xls`, `.xlsx`
- Uses `werkzeug.utils.secure_filename` for security

### Temporary Results
- Classification results stored in `TEMP_RESULTS` dict with session IDs
- Results expire and are cleaned up periodically

## API Response Format

Most API endpoints return JSON with consistent structure:
```json
{
  "success": true,
  "data": { ... }
}
// or
{
  "error": "Error message"
}
```

## Important Notes

- The app is primarily in Korean (UI and data)
- WeasyPrint requires system-level font packages (see render.yaml buildCommand)
- Excel processing uses Pandas with openpyxl/xlrd engines
- Large files are processed in memory using BytesIO
