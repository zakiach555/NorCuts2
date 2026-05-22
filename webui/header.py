import os
import sys

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
WORKING_DIR = os.path.dirname(CURRENT_DIR)
sys.path.append(WORKING_DIR)

from i18n.i18n import I18nAuto
i18n = I18nAuto()

badges = ""  # removed external badge requests — each one was a blocking HTTP round-trip on load

description = """
<div style="text-align:center; padding: 10px 0 4px 0;">
  <h2 style="margin:0 0 4px 0;">NorCuts2</h2>
  <p style="margin:0; color:#aaa; font-size:0.95em;">AI-powered viral clip cutter with Arabic subtitle support</p>
</div>
"""
