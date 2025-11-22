"""Email service using SendGrid."""

import logging

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

from audio_text_backend.config import Config
from audio_text_backend.model.transcription_job import TranscriptionJob

logger = logging.getLogger(__name__)


class EmailService:
    """Service for sending emails via SendGrid."""

    def __init__(self):
        """Initialize SendGrid client."""
        self.client = SendGridAPIClient(Config.email.sendgrid_api_key)
        self.from_email = Config.email.from_address
        self.from_name = Config.email.from_name

    def _format_processing_time(self, job: TranscriptionJob) -> str:
        """Format processing time in human-readable format."""
        if not job.processing_time_seconds:
            return "Unknown"

        minutes = int(job.processing_time_seconds // 60)
        seconds = int(job.processing_time_seconds % 60)

        if minutes > 0:
            return f"{minutes}m {seconds}s"
        else:
            return f"{seconds}s"

    def _build_html(self, job: TranscriptionJob) -> str:
        """Build HTML email content."""
        processing_time = self._format_processing_time(job)

        language_html = ""
        if job.language:
            confidence = (
                f" ({job.language_probability:.1%} confidence)" if job.language_probability else ""
            )
            language_html = (
                f'<p><span class="label">Detected Language:</span> {job.language}{confidence}</p>'
            )

        completed_date = (
            job.update_date.strftime("%B %d, %Y at %H:%M") if job.update_date else "Just now"
        )

        return f"""
        <html>
        <head>
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
                    line-height: 1.6;
                    color: #333;
                    max-width: 600px;
                    margin: 0 auto;
                    padding: 20px;
                }}
                .header {{
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    padding: 30px 20px;
                    border-radius: 10px 10px 0 0;
                    text-align: center;
                }}
                .content {{
                    background: #f9fafb;
                    padding: 30px;
                    border-radius: 0 0 10px 10px;
                }}
                .metadata {{
                    background: white;
                    padding: 15px;
                    border-radius: 8px;
                    margin-bottom: 20px;
                    border-left: 4px solid #667eea;
                }}
                .metadata p {{
                    margin: 5px 0;
                    font-size: 14px;
                }}
                .transcription {{
                    background: white;
                    padding: 20px;
                    border-radius: 8px;
                    white-space: pre-wrap;
                    word-wrap: break-word;
                    font-size: 15px;
                    line-height: 1.8;
                    border: 1px solid #e5e7eb;
                }}
                .footer {{
                    text-align: center;
                    margin-top: 30px;
                    padding-top: 20px;
                    border-top: 1px solid #e5e7eb;
                    color: #6b7280;
                    font-size: 12px;
                }}
                h1 {{
                    margin: 0;
                    font-size: 24px;
                }}
                h2 {{
                    color: #667eea;
                    font-size: 18px;
                    margin-top: 0;
                }}
                .label {{
                    font-weight: 600;
                    color: #4b5563;
                }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>🎙️ {self.from_name}</h1>
                <p style="margin: 10px 0 0 0; opacity: 0.9;">Your transcription is ready!</p>
            </div>
            <div class="content">
                <div class="metadata">
                    <p><span class="label">File:</span> {job.filename}</p>
                    <p><span class="label">Processing Time:</span> {processing_time}</p>
                    <p><span class="label">Model:</span> {job.whisper_model or "base"}</p>
                    {language_html}
                    <p><span class="label">Completed:</span> {completed_date}</p>
                </div>

                <h2>Transcription Result:</h2>
                <div class="transcription">{job.result_text or "No transcription available."}</div>

                <div class="footer">
                    <p>This is an automated email from {self.from_name}.</p>
                    <p>Powered by Whisper AI • Fast & Accurate Transcription</p>
                </div>
            </div>
        </body>
        </html>
        """

    def _build_text(self, job: TranscriptionJob) -> str:
        """Build plain text email content."""
        processing_time = self._format_processing_time(job)

        language_info = ""
        if job.language:
            confidence = (
                f" ({job.language_probability:.1%} confidence)" if job.language_probability else ""
            )
            language_info = f"\nDetected Language: {job.language}{confidence}"

        completed_date = (
            job.update_date.strftime("%B %d, %Y at %H:%M") if job.update_date else "Just now"
        )

        return f"""
{self.from_name} - Audio Transcription

Your transcription is ready!

File: {job.filename}
Processing Time: {processing_time}
Model: {job.whisper_model or "base"}{language_info}
Completed: {completed_date}

Transcription Result:
{"-" * 50}
{job.result_text or "No transcription available."}
{"-" * 50}

---
This is an automated email from {self.from_name}.
Powered by Whisper AI • Fast & Accurate Transcription
        """

    def send_transcription(self, job: TranscriptionJob, recipient_email: str) -> bool:
        """Send transcription results via email.

        Args:
            job: TranscriptionJob with completed transcription
            recipient_email: Email address to send results to

        Returns:
            bool: True if email sent successfully, False otherwise

        """
        try:
            subject = f"Your Audio Transcription - {job.filename}"

            # Build email content
            html_content = self._build_html(job)
            text_content = self._build_text(job)

            # Create message
            message = Mail(
                from_email=(self.from_email, self.from_name),
                to_emails=recipient_email,
                subject=subject,
                plain_text_content=text_content,
                html_content=html_content,
            )

            # Send email
            response = self.client.send(message)

            if response.status_code in [200, 201, 202]:
                logger.info(f"Email sent successfully to {recipient_email} for job {job.id}")
                return True
            else:
                logger.error(f"Failed to send email: {response.status_code} - {response.body}")
                return False

        except Exception as e:
            logger.error(f"Error sending email for job {job.id}: {e}")
            return False


# Singleton instance
_email_service: EmailService | None = None


def get_email_service() -> EmailService:
    """Get or create email service singleton."""
    global _email_service
    if _email_service is None:
        _email_service = EmailService()
    return _email_service
