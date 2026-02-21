from ..core.resources import ServerlessEndpoint, JobOutput


class ServerlessEndpointStub:
    """Adapter class to make Runpod endpoints requests."""

    def __init__(self, server: ServerlessEndpoint):
        self.server = server

    def prepare_payload(self, func, *args, **kwargs) -> dict:
        return func(*args, **kwargs)

    async def execute(self, payload: dict, sync: bool = False) -> JobOutput:
        """
        Executes a serverless endpoint request with the payload.
        Returns a JobOutput object.
        """
        if sync:
            return await self.server.runsync(payload)
        else:
            return await self.server.run(payload)

    def handle_response(self, response: JobOutput):
        if response.output:
            return response.output

        if response.error:
            raise Exception(f"Remote execution failed: {response.error}")

        raise ValueError("Invalid response from server")
