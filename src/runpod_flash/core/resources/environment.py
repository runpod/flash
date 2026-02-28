from typing import Dict, Optional
from dotenv import dotenv_values, find_dotenv


class EnvironmentVars:
    def __init__(self):
        # Store environment variables from .env file
        self.env = self._load_env()

    def _load_env(self) -> Dict[str, str]:
        """
        Loads environment variables specifically from the .env file
        and returns them as a dictionary.

        Returns:
            Dict[str, str]: Dictionary containing environment variables from .env file
        """
        # Use dotenv_values instead of load_dotenv to get only variables from .env
        # usecwd=True walks up from CWD (user's project) instead of from the
        # package source file location, which matters for editable installs.
        return dict(dotenv_values(find_dotenv(usecwd=True)))

    def get_env(self) -> Dict[str, str]:
        """
        Returns the dictionary of environment variables.

        Returns:
            Dict[str, str]: Dictionary containing environment variables
        """
        return self.env

    def get_value(self, key: str, default: str = None) -> Optional[str]:
        """
        Gets a specific environment variable by key.

        Args:
            key (str): The environment variable key
            default (str, optional): Default value if key doesn't exist

        Returns:
            Optional[str]: Value of the environment variable or default
        """
        return self.env.get(key, default)
