name: Scrape Single Listing (Test)

on:
  workflow_dispatch:
    inputs:
      listing_url:
        description: "Mudah listing URL to test"
        required: true
        default: "https://www.mudah.my/ara-green-115014914.htm"

jobs:
  scrape-one:
    name: Scrape One Listing
    runs-on: ubuntu-latest

    steps:
      - name: Checkout repo
        uses: actions/checkout@v4

      - name: Set up Python 3.11
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: pip install requests==2.32.3

      - name: Scrape single listing
        run: python scrape_single.py "${{ github.event.inputs.listing_url }}"
