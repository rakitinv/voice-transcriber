"""
S3 / MinIO client wrapper.

Provides helpers to store and retrieve:
- audio files
- transcripts (JSON and Markdown)
- summaries
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

import boto3
from botocore.client import BaseClient
from botocore.exceptions import ClientError

from .audio_format import s3_audio_object_name
from .config import app_config
from .logging import logger
from .security import decrypt_data, encrypt_data


class S3Storage:
    """S3/MinIO storage client with per-user encryption."""

    def __init__(self):
        self.client: BaseClient = boto3.client(
            "s3",
            endpoint_url=app_config.s3.endpoint,
            aws_access_key_id=app_config.s3.access_key,
            aws_secret_access_key=app_config.s3.secret_key,
        )
        self.bucket = app_config.s3.bucket
        self._ensure_bucket_exists()

    def _ensure_bucket_exists(self) -> None:
        """Ensure the S3 bucket exists, create if it doesn't."""
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError:
            try:
                self.client.create_bucket(Bucket=self.bucket)
                logger.info(f"Created S3 bucket: {self.bucket}")
            except ClientError as e:
                logger.error(f"Failed to create bucket {self.bucket}: {e}")
                raise

    def _get_key(self, user_id: str, conversation_id: str, filename: str) -> str:
        """Generate S3 key for a file."""
        return f"users/{user_id}/conversations/{conversation_id}/{filename}"

    def upload_audio(
        self,
        audio_data: bytes,
        user_id: str,
        conversation_id: str,
        *,
        audio_object_ext: str = "webm",
        encrypt: bool = True,
    ) -> str:
        """
        Upload audio file to S3.

        Args:
            audio_data: Raw audio bytes
            user_id: User ID
            conversation_id: Conversation ID
            audio_object_ext: расширение без точки (webm, mp3, wav, …) — имя ключа audio.<ext>
            encrypt: Whether to encrypt the data

        Returns:
            S3 key of the uploaded file
        """
        key = self._get_key(user_id, conversation_id, s3_audio_object_name(audio_object_ext))
        data = encrypt_data(audio_data, user_id) if encrypt else audio_data
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data)
        logger.info(f"Uploaded audio to {key}")
        return key

    def download_audio(
        self,
        user_id: str,
        conversation_id: str,
        *,
        audio_object_ext: str = "webm",
        decrypt: bool = True,
    ) -> bytes:
        """
        Download audio file from S3.

        Args:
            user_id: User ID
            conversation_id: Conversation ID
            audio_object_ext: расширение без точки, как при upload_audio
            decrypt: Whether to decrypt the data

        Returns:
            Raw audio bytes
        """
        key = self._get_key(user_id, conversation_id, s3_audio_object_name(audio_object_ext))
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        data = response["Body"].read()
        return decrypt_data(data, user_id) if decrypt else data

    def upload_transcript_json(
        self, transcript: Dict[str, Any], user_id: str, conversation_id: str, encrypt: bool = True
    ) -> str:
        """Upload transcript JSON to S3."""
        key = self._get_key(user_id, conversation_id, "transcript.json")
        data = json.dumps(transcript, indent=2).encode("utf-8")
        data = encrypt_data(data, user_id) if encrypt else data
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data)
        logger.info(f"Uploaded transcript JSON to {key}")
        return key

    def download_transcript_json(
        self, user_id: str, conversation_id: str, decrypt: bool = True
    ) -> Dict[str, Any]:
        """Download transcript JSON from S3."""
        key = self._get_key(user_id, conversation_id, "transcript.json")
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        data = response["Body"].read()
        if decrypt:
            data = decrypt_data(data, user_id)
        return json.loads(data.decode("utf-8"))

    def upload_transcript_markdown(
        self, markdown: str, user_id: str, conversation_id: str, encrypt: bool = True
    ) -> str:
        """Upload transcript Markdown to S3."""
        key = self._get_key(user_id, conversation_id, "transcript.md")
        data = markdown.encode("utf-8")
        data = encrypt_data(data, user_id) if encrypt else data
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data)
        logger.info(f"Uploaded transcript Markdown to {key}")
        return key

    def download_transcript_markdown(
        self, user_id: str, conversation_id: str, decrypt: bool = True
    ) -> str:
        """Download transcript Markdown from S3."""
        key = self._get_key(user_id, conversation_id, "transcript.md")
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        data = response["Body"].read()
        if decrypt:
            data = decrypt_data(data, user_id)
        return data.decode("utf-8")

    def upload_summary(
        self, summary: str, user_id: str, conversation_id: str, encrypt: bool = True
    ) -> str:
        """Upload summary Markdown to S3."""
        key = self._get_key(user_id, conversation_id, "summary.md")
        data = summary.encode("utf-8")
        data = encrypt_data(data, user_id) if encrypt else data
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data)
        logger.info(f"Uploaded summary to {key}")
        return key

    def download_summary(
        self, user_id: str, conversation_id: str, decrypt: bool = True
    ) -> Optional[str]:
        """Download summary Markdown from S3."""
        key = self._get_key(user_id, conversation_id, "summary.md")
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
            data = response["Body"].read()
            if decrypt:
                data = decrypt_data(data, user_id)
            return data.decode("utf-8")
        except ClientError:
            return None

    def _recording_session_summary_key(self, user_id: str, recording_session_id: str) -> str:
        return f"users/{user_id}/recording_sessions/{recording_session_id}/summary.md"

    def upload_recording_session_summary(
        self,
        summary: str,
        user_id: str,
        recording_session_id: str,
        *,
        encrypt: bool = True,
    ) -> str:
        """Persist §7.6 chain summary next to user/session namespace."""
        key = self._recording_session_summary_key(user_id, recording_session_id)
        data = summary.encode("utf-8")
        data = encrypt_data(data, user_id) if encrypt else data
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data)
        logger.info(f"Uploaded recording_session summary to {key}")
        return key

    def download_recording_session_summary(
        self, user_id: str, recording_session_id: str, decrypt: bool = True
    ) -> Optional[str]:
        key = self._recording_session_summary_key(user_id, recording_session_id)
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
            data = response["Body"].read()
            if decrypt:
                data = decrypt_data(data, user_id)
            return data.decode("utf-8")
        except ClientError:
            return None

    def delete_conversation(self, user_id: str, conversation_id: str) -> None:
        """Delete all files for a conversation."""
        prefix = f"users/{user_id}/conversations/{conversation_id}/"
        paginator = self.client.get_paginator("list_objects_v2")
        deleted = 0
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents") or []:
                key = obj["Key"]
                # delete_object avoids DeleteObjects Content-MD5 requirement on strict S3 backends.
                self.client.delete_object(Bucket=self.bucket, Key=key)
                deleted += 1
        logger.info(f"Deleted conversation files: {prefix} ({deleted} objects)")


# Global storage instance
storage = S3Storage()