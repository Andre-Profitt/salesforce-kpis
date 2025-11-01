"""
Salesforce REST API client.

Provides methods for common Salesforce operations: queries, updates, email sends.
"""

import os
from typing import Any, Dict, List, Optional
import requests
import structlog
from src.auth.jwt_auth import SalesforceJWTAuth

logger = structlog.get_logger()


class SalesforceAPIClient:
    """Client for Salesforce REST API operations."""

    def __init__(self, auth: SalesforceJWTAuth, api_version: str = "59.0"):
        """
        Initialize Salesforce API client.

        Args:
            auth: Configured SalesforceJWTAuth instance
            api_version: Salesforce API version (default: 59.0)
        """
        self.auth = auth
        self.api_version = api_version
        self.base_url = f"{auth.instance_url}/services/data/v{api_version}"

    def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None,
        params: Optional[Dict] = None
    ) -> requests.Response:
        """
        Make authenticated request to Salesforce API.

        Args:
            method: HTTP method (GET, POST, PATCH, DELETE)
            endpoint: API endpoint (without base URL)
            data: Request body (for POST/PATCH)
            params: Query parameters

        Returns:
            Response object
        """
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        headers = self.auth.get_auth_headers()

        logger.debug("api_request", method=method, url=url)

        try:
            response = requests.request(
                method=method,
                url=url,
                headers=headers,
                json=data,
                params=params,
                timeout=30
            )
            response.raise_for_status()
            return response

        except requests.exceptions.RequestException as e:
            logger.error("api_request_failed", error=str(e), url=url)
            raise

    def query(self, soql: str) -> List[Dict[str, Any]]:
        """
        Execute SOQL query.

        Args:
            soql: SOQL query string

        Returns:
            List of records
        """
        logger.info("executing_soql", query=soql)

        response = self._make_request(
            method='GET',
            endpoint='query',
            params={'q': soql}
        )

        result = response.json()
        records = result.get('records', [])

        logger.info("query_complete", record_count=len(records))
        return records

    def get_record(self, sobject_type: str, record_id: str, fields: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Get a single record by ID.

        Args:
            sobject_type: SObject type (e.g., 'Lead', 'Task')
            record_id: Salesforce record ID
            fields: Optional list of fields to retrieve

        Returns:
            Record dictionary
        """
        endpoint = f"sobjects/{sobject_type}/{record_id}"

        params = {}
        if fields:
            params['fields'] = ','.join(fields)

        response = self._make_request('GET', endpoint, params=params)
        return response.json()

    def update_record(self, sobject_type: str, record_id: str, data: Dict[str, Any]) -> bool:
        """
        Update a record (PATCH).

        Args:
            sobject_type: SObject type (e.g., 'Lead', 'Task')
            record_id: Salesforce record ID
            data: Fields to update

        Returns:
            True if successful
        """
        endpoint = f"sobjects/{sobject_type}/{record_id}"

        logger.info("updating_record", sobject=sobject_type, id=record_id, fields=list(data.keys()))

        self._make_request('PATCH', endpoint, data=data)

        logger.info("record_updated", sobject=sobject_type, id=record_id)
        return True

    def create_record(self, sobject_type: str, data: Dict[str, Any]) -> str:
        """
        Create a new record (POST).

        Args:
            sobject_type: SObject type (e.g., 'Task', 'EmailMessage')
            data: Record data

        Returns:
            Created record ID
        """
        endpoint = f"sobjects/{sobject_type}"

        logger.info("creating_record", sobject=sobject_type, fields=list(data.keys()))

        response = self._make_request('POST', endpoint, data=data)
        result = response.json()

        record_id = result.get('id')
        logger.info("record_created", sobject=sobject_type, id=record_id)

        return record_id

    def send_email_simple(
        self,
        to_addresses: List[str],
        subject: str,
        body: str,
        html_body: Optional[str] = None
    ) -> bool:
        """
        Send email via Salesforce Simple Email Action.

        Args:
            to_addresses: List of recipient email addresses
            subject: Email subject
            body: Plain text email body
            html_body: Optional HTML email body

        Returns:
            True if successful
        """
        endpoint = "actions/standard/emailSimple"

        email_input = {
            "emailSubject": subject,
            "emailBody": html_body if html_body else body,
            "toAddresses": to_addresses
        }

        if html_body:
            email_input["emailBodyFormat"] = "HTML"

        data = {"inputs": [email_input]}

        logger.info("sending_email", to=to_addresses, subject=subject)

        response = self._make_request('POST', endpoint, data=data)
        result = response.json()

        success = result.get('outputs', [{}])[0].get('success', False)

        if success:
            logger.info("email_sent", to=to_addresses)
        else:
            logger.error("email_send_failed", result=result)

        return success

    def get_lead_first_response(self, lead_id: str) -> Optional[Dict[str, Any]]:
        """
        Get the first response (Task or EmailMessage) for a Lead.

        Args:
            lead_id: Lead ID

        Returns:
            Dictionary with first response details or None
        """
        # Check for earliest completed Task
        task_soql = f"""
            SELECT Id, CreatedDate, OwnerId, Owner.Name, Type
            FROM Task
            WHERE WhoId = '{lead_id}'
            AND Status = 'Completed'
            AND Type IN ('Call', 'Email', 'Meeting')
            ORDER BY CreatedDate ASC
            LIMIT 1
        """

        tasks = self.query(task_soql)

        # Check for earliest EmailMessage (Enhanced Email)
        email_soql = f"""
            SELECT Id, MessageDate, CreatedById, CreatedBy.Name, FromAddress
            FROM EmailMessage
            WHERE RelatedToId = '{lead_id}'
            ORDER BY MessageDate ASC
            LIMIT 1
        """

        emails = self.query(email_soql)

        # Determine which came first
        first_response = None

        if tasks and emails:
            task_date = tasks[0]['CreatedDate']
            email_date = emails[0]['MessageDate']

            if task_date < email_date:
                first_response = {
                    'type': 'Task',
                    'datetime': task_date,
                    'user_id': tasks[0]['OwnerId'],
                    'user_name': tasks[0]['Owner']['Name'],
                    'record_id': tasks[0]['Id']
                }
            else:
                first_response = {
                    'type': 'EmailMessage',
                    'datetime': email_date,
                    'user_id': emails[0]['CreatedById'],
                    'user_name': emails[0]['CreatedBy']['Name'],
                    'record_id': emails[0]['Id']
                }
        elif tasks:
            first_response = {
                'type': 'Task',
                'datetime': tasks[0]['CreatedDate'],
                'user_id': tasks[0]['OwnerId'],
                'user_name': tasks[0]['Owner']['Name'],
                'record_id': tasks[0]['Id']
            }
        elif emails:
            first_response = {
                'type': 'EmailMessage',
                'datetime': emails[0]['MessageDate'],
                'user_id': emails[0]['CreatedById'],
                'user_name': emails[0]['CreatedBy']['Name'],
                'record_id': emails[0]['Id']
            }

        return first_response

    def update_lead_first_response(
        self,
        lead_id: str,
        first_response_at: str,
        first_response_user_id: str,
        ttfr_minutes: float
    ) -> bool:
        """
        Update Lead with first response tracking fields.

        Args:
            lead_id: Lead ID
            first_response_at: ISO datetime of first response
            first_response_user_id: User who made first response
            ttfr_minutes: Time to first response in minutes

        Returns:
            True if successful
        """
        return self.update_record(
            'Lead',
            lead_id,
            {
                'First_Response_At__c': first_response_at,
                'First_Response_User__c': first_response_user_id,
                'Time_to_First_Response__c': ttfr_minutes
            }
        )
