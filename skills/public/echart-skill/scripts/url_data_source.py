"""
URL Data Source Module.

Provides async HTTP data fetching with authentication support:
- URLDataSourceConfig: Pydantic configuration model
- BasicAuthConfig: Basic authentication configuration
- BearerAuthConfig: Bearer token authentication configuration
- APIKeyHeaderAuthConfig: API Key in header authentication
- APIKeyQueryParamAuthConfig: API Key in query parameter authentication
- OAuth2ClientCredentialsConfig: OAuth2 Client Credentials flow
- URLDataSource: Async HTTP client with retry and parsing

Usage:
    from scripts.url_data_source import URLDataSource, URLDataSourceConfig

    config = URLDataSourceConfig(
        url="https://api.example.com/data",
        format="json",
        table_name="api_data"
    )

    source = URLDataSource(config)
    records = await source.fetch_and_parse()
"""

import time
import ipaddress
from typing import Literal, Optional, Union
from urllib.parse import urlencode, urlparse, parse_qs, urlunparse

from pydantic import BaseModel, Field, SecretStr, field_validator
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import structlog
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from validators import validate_table_name

logger = structlog.get_logger(__name__)

MAX_RETRIES = 3
MAX_RESPONSE_SIZE = 100 * 1024 * 1024  # 100MB


class ServerError(Exception):
    """Exception for 5xx server errors that should trigger retry."""
    pass


class BasicAuthConfig(BaseModel):
    """Basic authentication configuration.

    Attributes:
        type: Authentication type, always 'basic'
        username: Username for Basic Auth
        password: Password for Basic Auth (stored as SecretStr)
    """
    type: Literal["basic"] = "basic"
    username: str = Field(description="Username for Basic Auth")
    password: SecretStr = Field(description="Password for Basic Auth")


class BearerAuthConfig(BaseModel):
    """Bearer token authentication configuration.

    Attributes:
        type: Authentication type, always 'bearer'
        token: Bearer token value (stored as SecretStr)
    """
    type: Literal["bearer"] = "bearer"
    token: SecretStr = Field(description="Bearer token value")


class APIKeyHeaderAuthConfig(BaseModel):
    """API Key in HTTP header authentication.
    
    Attributes:
        type: Authentication type, always 'api_key_header'
        header_name: Header name for the API key (default: X-API-Key)
        key: API key value (stored as SecretStr)
    """
    type: Literal["api_key_header"] = "api_key_header"
    header_name: str = Field(default="X-API-Key", description="Header name for API key")
    key: SecretStr = Field(description="API key value")


class APIKeyQueryParamAuthConfig(BaseModel):
    """API Key in URL query parameter authentication.
    
    Attributes:
        type: Authentication type, always 'api_key_query'
        param_name: Query parameter name (default: api_key)
        key: API key value (stored as SecretStr)
    """
    type: Literal["api_key_query"] = "api_key_query"
    param_name: str = Field(default="api_key", description="Query parameter name")
    key: SecretStr = Field(description="API key value")


class OAuth2ClientCredentialsConfig(BaseModel):
    """OAuth2 Client Credentials flow configuration.
    
    Attributes:
        type: Authentication type, always 'oauth2_client_credentials'
        token_url: OAuth2 token endpoint URL
        client_id: OAuth2 client ID
        client_secret: OAuth2 client secret (stored as SecretStr)
        scope: Optional OAuth2 scope
    """
    type: Literal["oauth2_client_credentials"] = "oauth2_client_credentials"
    token_url: str = Field(description="OAuth2 token endpoint URL")
    client_id: str = Field(description="OAuth2 client ID")
    client_secret: SecretStr = Field(description="OAuth2 client secret")
    scope: Optional[str] = Field(default=None, description="OAuth2 scope")


class OAuth2TokenManager:
    """Manages OAuth2 tokens with automatic refresh.
    
    Caches tokens and refreshes when expired or on 401 errors.
    """
    
    def __init__(self, config: OAuth2ClientCredentialsConfig):
        self.config = config
        self._token: Optional[str] = None
        self._expires_at: Optional[float] = None
    
    async def get_token(self) -> str:
        if self._token and self._expires_at and time.time() < self._expires_at - 60:
            return self._token
        return await self._fetch_new_token()
    
    async def _fetch_new_token(self) -> str:
        async with httpx.AsyncClient() as client:
            data = {"grant_type": "client_credentials"}
            if self.config.scope:
                data["scope"] = self.config.scope
            
            response = await client.post(
                self.config.token_url,
                data=data,
                auth=httpx.BasicAuth(
                    self.config.client_id,
                    self.config.client_secret.get_secret_value()
                )
            )
            response.raise_for_status()
            token_data = response.json()
            
            self._token = token_data["access_token"]
            self._expires_at = time.time() + token_data.get("expires_in", 3600)
            
            logger.info("OAuth2 token fetched", expires_in=token_data.get("expires_in", 3600))
            return self._token
    
    def invalidate(self) -> None:
        self._token = None
        self._expires_at = None


AuthConfig = Union[
    BasicAuthConfig, 
    BearerAuthConfig, 
    APIKeyHeaderAuthConfig, 
    APIKeyQueryParamAuthConfig,
    OAuth2ClientCredentialsConfig
]


class URLDataSourceConfig(BaseModel):
    """Configuration for URL data source import.

    Attributes:
        url: HTTP/HTTPS URL to fetch data from
        format: Data format, either 'json' or 'csv'
        table_name: Target table name for the imported data
        auth: Optional authentication configuration
        timeout: Request timeout in seconds (1.0 - 300.0)
    """
    url: str = Field(description="HTTP/HTTPS URL to fetch data from")
    format: Literal["json", "csv"] = Field(description="Data format")
    table_name: str = Field(description="Target table name")
    auth: Optional[AuthConfig] = Field(default=None, description="Authentication config")
    allow_private_networks: bool = Field(
        default=False,
        description="Allow localhost/private/link-local IP targets"
    )
    timeout: float = Field(
        default=30.0,
        ge=1.0,
        le=300.0,
        description="Request timeout in seconds"
    )

    @field_validator('url')
    @classmethod
    def validate_url(cls, v: str) -> str:
        parsed = urlparse(v)
        if parsed.scheme not in ("http", "https"):
            raise ValueError("URL must start with http:// or https://")
        if not parsed.hostname:
            raise ValueError("URL must include a hostname")
        return v

    @field_validator('table_name')
    @classmethod
    def validate_target_table(cls, v: str) -> str:
        return validate_table_name(v)
    
    @field_validator('auth', mode='before')
    @classmethod
    def validate_auth_dict(cls, v):
        if isinstance(v, dict):
            auth_type = v.get('type')
            type_map = {
                'basic': BasicAuthConfig,
                'bearer': BearerAuthConfig,
                'api_key_header': APIKeyHeaderAuthConfig,
                'api_key_query': APIKeyQueryParamAuthConfig,
                'oauth2_client_credentials': OAuth2ClientCredentialsConfig,
            }
            if auth_type in type_map:
                return type_map[auth_type](**v)
        return v


class URLDataSource:
    """Async HTTP data source fetcher with authentication support.

    Provides:
    - Async HTTP fetching with retry logic
    - Basic Auth, Bearer token, API Key, and OAuth2 authentication
    - Response size validation
    - JSON and CSV parsing

    Attributes:
        config: URLDataSource configuration
    """

    def __init__(self, config: URLDataSourceConfig):
        self.config = config
        self._oauth2_manager: Optional[OAuth2TokenManager] = None
        if isinstance(config.auth, OAuth2ClientCredentialsConfig):
            self._oauth2_manager = OAuth2TokenManager(config.auth)

    def _build_auth(self) -> Optional[httpx.Auth]:
        """Build httpx auth from configuration.

        Returns:
            httpx.Auth for Basic Auth, None otherwise (Bearer handled via headers)
        """
        if self.config.auth is None:
            return None

        if isinstance(self.config.auth, BasicAuthConfig):
            return httpx.BasicAuth(
                self.config.auth.username,
                self.config.auth.password.get_secret_value()
            )

        # Bearer token is handled via headers
        return None

    def _build_headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json, text/csv, text/plain",
            "User-Agent": "echart-skill/1.0"
        }

        if isinstance(self.config.auth, BearerAuthConfig):
            headers["Authorization"] = f"Bearer {self.config.auth.token.get_secret_value()}"
        elif isinstance(self.config.auth, APIKeyHeaderAuthConfig):
            headers[self.config.auth.header_name] = self.config.auth.key.get_secret_value()

        return headers
    
    def _build_url_with_auth(self) -> str:
        """Build URL with query params for API Key auth.
        
        Returns:
            URL with query params added if API Key query param auth
        """
        if isinstance(self.config.auth, APIKeyQueryParamAuthConfig):
            parsed = urlparse(self.config.url)
            params = parse_qs(parsed.query)
            params[self.config.auth.param_name] = self.config.auth.key.get_secret_value()
            new_query = urlencode(params, doseq=True)
            return urlunparse(parsed._replace(query=new_query))
        
        return self.config.url

    def _validate_request_url(self, url: str) -> None:
        if self.config.allow_private_networks:
            return

        parsed = urlparse(url)
        host = parsed.hostname
        if not host:
            raise ValueError("URL must include a hostname")

        normalized_host = host.strip("[]").lower()
        if normalized_host in {"localhost", "localhost.localdomain"} or normalized_host.endswith(".localhost"):
            raise ValueError("Private or localhost URLs are not allowed")

        try:
            ip = ipaddress.ip_address(normalized_host)
        except ValueError:
            return

        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise ValueError("Private or localhost URLs are not allowed")

    def _validate_response_size(self, response: httpx.Response) -> None:
        content_length = response.headers.get('content-length')
        if content_length and int(content_length) > MAX_RESPONSE_SIZE:
            raise ValueError(
                f"Response too large: {int(content_length) / 1024 / 1024:.1f}MB > 100MB limit"
            )

        if len(response.content) > MAX_RESPONSE_SIZE:
            raise ValueError(
                f"Response too large: {len(response.content) / 1024 / 1024:.1f}MB > 100MB limit"
            )

    @retry(
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential(multiplier=1, min=1, max=4),
        retry=retry_if_exception_type(ServerError),
        reraise=True
    )
    async def fetch(self) -> str:
        timeout = httpx.Timeout(self.config.timeout)
        
        url = self._build_url_with_auth()
        self._validate_request_url(url)
        headers = self._build_headers()
        
        if self._oauth2_manager:
            token = await self._oauth2_manager.get_token()
            headers["Authorization"] = f"Bearer {token}"

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(
                url,
                auth=self._build_auth(),
                headers=headers
            )
            self._validate_request_url(str(response.url))
            
            if response.status_code == 401 and self._oauth2_manager:
                self._oauth2_manager.invalidate()
                token = await self._oauth2_manager.get_token()
                headers["Authorization"] = f"Bearer {token}"
                response = await client.get(url, auth=self._build_auth(), headers=headers)
                self._validate_request_url(str(response.url))

            if response.status_code >= 500:
                raise ServerError(
                    f"Server error {response.status_code}: {response.text[:200]}"
                )

            response.raise_for_status()

            self._validate_response_size(response)

            return response.text

    async def post(self, data: dict) -> str:
        """Make POST request with JSON body.
        
        Args:
            data: JSON body as dict
            
        Returns:
            Response content as string
        """
        return await self._request_with_body("POST", data)

    async def put(self, data: dict) -> str:
        """Make PUT request with JSON body.
        
        Args:
            data: JSON body as dict
            
        Returns:
            Response content as string
        """
        return await self._request_with_body("PUT", data)

    async def delete(self) -> str:
        """Make DELETE request.
        
        Returns:
            Response content as string
        """
        return await self._request_with_body("DELETE")

    async def _request_with_body(self, method: str, data: Optional[dict] = None) -> str:
        """Execute HTTP request with optional body.
        
        Args:
            method: HTTP method (POST, PUT, DELETE)
            data: Optional JSON body
            
        Returns:
            Response content as string
        """
        timeout = httpx.Timeout(self.config.timeout)
        url = self._build_url_with_auth()
        self._validate_request_url(url)
        headers = self._build_headers()
        headers["Content-Type"] = "application/json"
        
        if self._oauth2_manager:
            token = await self._oauth2_manager.get_token()
            headers["Authorization"] = f"Bearer {token}"

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.request(
                method,
                url,
                auth=self._build_auth(),
                headers=headers,
                json=data
            )
            self._validate_request_url(str(response.url))
            
            if response.status_code == 401 and self._oauth2_manager:
                self._oauth2_manager.invalidate()
                token = await self._oauth2_manager.get_token()
                headers["Authorization"] = f"Bearer {token}"
                response = await client.request(method, url, auth=self._build_auth(), headers=headers, json=data)
                self._validate_request_url(str(response.url))

            if response.status_code >= 500:
                raise ServerError(
                    f"Server error {response.status_code}: {response.text[:200]}"
                )

            response.raise_for_status()

            self._validate_response_size(response)

            return response.text

    async def fetch_and_parse(self) -> list[dict]:
        """Fetch and parse data from URL.

        Returns:
            List of dictionaries representing rows
        """
        content = await self.fetch()

        if self.config.format == "json":
            return self._parse_json(content)
        else:
            return self._parse_csv(content)

    def _parse_json(self, content: str) -> list[dict]:
        """Parse JSON content and flatten nested structures.

        Args:
            content: Raw JSON string

        Returns:
            List of dictionaries

        Raises:
            ValueError: If JSON is invalid or not an array
        """
        import json
        import pandas as pd
        import sys
        import os

        # Add project root to path for imports
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from scripts.data_importer import clean_column_names

        data = json.loads(content)

        # Auto-detect array location
        if isinstance(data, dict):
            # Check common wrapper keys
            for key in ['data', 'results', 'items', 'records', 'rows']:
                if key in data and isinstance(data[key], list):
                    data = data[key]
                    break
            else:
                # Single object, wrap in list
                data = [data]

        if not isinstance(data, list):
            raise ValueError(f"Expected JSON array, got {type(data).__name__}")

        if not data:
            return []

        # Flatten nested objects using pandas
        df = pd.json_normalize(data, sep='_')

        # Clean column names
        df.columns = clean_column_names(df.columns.tolist())

        return df.to_dict(orient='records')

    def _parse_csv(self, content: str) -> list[dict]:
        """Parse CSV content into list of dicts.

        Args:
            content: Raw CSV string

        Returns:
            List of dictionaries
        """
        import io
        import pandas as pd
        import sys
        import os

        # Add project root to path for imports
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from scripts.data_importer import clean_column_names

        df = pd.read_csv(io.StringIO(content))

        # Clean column names
        df.columns = clean_column_names(df.columns.tolist())

        return df.to_dict(orient='records')


def infer_schema_from_json(data: Union[list[dict], dict]) -> dict[str, str]:
    """Infer column types from JSON data.

    Handles nested structures by flattening with underscore notation.
    Returns a mapping of column names to DuckDB types.

    Args:
        data: JSON data (list of dicts or single dict)

    Returns:
        Dict mapping column names to DuckDB types (INTEGER, REAL, TEXT)
    """
    import pandas as pd

    # Handle single object response
    if isinstance(data, dict):
        # Check if it's a wrapper with data array
        for key in ['data', 'results', 'items', 'records']:
            if key in data and isinstance(data[key], list):
                data = data[key]
                break
        else:
            data = [data]  # Single record

    if not data:
        return {}

    # Flatten nested structures
    df = pd.json_normalize(data, sep='_')

    # Infer types - map pandas dtypes to DuckDB types
    type_map = {
        'int64': 'INTEGER',
        'Int64': 'INTEGER',
        'float64': 'REAL',
        'Float64': 'REAL',
        'bool': 'INTEGER',
        'boolean': 'INTEGER',
        'object': 'TEXT',
        'datetime64[ns]': 'TEXT',  # Store as ISO string
    }

    schema = {}
    for col in df.columns:
        pandas_type = str(df[col].dtype)
        schema[col] = type_map.get(pandas_type, 'TEXT')

    return schema
