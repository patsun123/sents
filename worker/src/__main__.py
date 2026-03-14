"""
Module entry point — enables ``python -m worker`` invocation.
"""
import asyncio

from .main import main

asyncio.run(main())
