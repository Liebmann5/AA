# Configuration

The AutoApply Agent needs to know about you to apply for jobs on your behalf. All of your personal data, work history, and job preferences are stored in a single, secure file on your computer called `default_profile.json`.

This file is your "persona." The agent reads from this file every time it runs.

## The First Run & The Setup Wizard

The first time you run the application, it will detect that you don't have a profile. It will automatically:
1.  Create the `default_profile.json` file for you from a template.
2.  Open the **Setup Wizard** to guide you.

The wizard will show you the exact path to your new profile file and provide helpful buttons:
*   **Open Profile to Edit:** This will open `default_profile.json` in your computer's default text editor.
*   **Set Resume Path...:** This is a powerful helper that opens a file browser, allowing you to find your resume. It will then automatically write the correct, full path into your profile file for you.

!!! warning "Action Required"
    You **must** open your `default_profile.json` file and fill in your personal information before the agent can work correctly.

---

## Structure of Your Profile

The profile is a JSON file, which is a simple text-based format for storing data. It's organized into sections. Here is a breakdown of each section and what the fields mean.

### `personal_info`

This section contains your basic contact and identity information.

```json
"personal_info": {
  "first_name": "Bruce",
  "last_name": "Dickinson",
  "email": "BruceDickinson@gmail.com",
  "phone_number": "911-555-1980",
  "street_address": "123 Iron Maiden Ave",
  "city": "London",
  "state": "N/A",
  "zip_code": "E10",
  "country": "United Kingdom",
  "resume_path": "C:/Users/user/Desktop/ResumeTesties.pdf"
}