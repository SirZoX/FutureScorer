# args.py
"""
Centralized command-line argument parsing for FutureScorer bot.
All argument flags are initialized to False and set to True if present in sys.argv.
Import this module anywhere to access argument flags.
"""
import sys

isSandbox = False
isForce = False
generatePlots = False

if '-test' in sys.argv:
    isSandbox = True
if '-force' in sys.argv:
    isForce = True
if '-plots' in sys.argv:
    generatePlots = True
