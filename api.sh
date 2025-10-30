#!/bin/bash

# API Testing Script
# Usage: ./api-test.sh METHOD ROUTE [DATA] [OPTIONS]
# Example: ./api-test.sh POST /api/categories '{"name":"Test","description":"Desc"}'

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default values
BASE_URL="${API_BASE_URL:-http://localhost}"
CONTENT_TYPE="application/json"
ACCEPT="application/json"

# Function to display usage
usage() {
    echo -e "${BLUE}Usage:${NC}"
    echo "  $0 METHOD ROUTE [DATA] [OPTIONS]"
    echo ""
    echo -e "${BLUE}Examples:${NC}"
    echo "  $0 GET /api/categories"
    echo "  $0 POST /api/categories '{\"name\":\"Test\",\"description\":\"Desc\"}'"
    echo "  $0 PUT /api/categories/1 '{\"name\":\"Updated\"}'"
    echo "  $0 DELETE /api/categories/1"
    echo ""
    echo -e "${BLUE}Options:${NC}"
    echo "  -h, --help              Show this help message"
    echo "  -b, --base-url URL      Set base URL (default: http://localhost)"
    echo "  -t, --token TOKEN       Add Bearer token for authentication"
    echo "  -c, --content-type TYPE Set Content-Type header (default: application/json)"
    echo "  -a, --accept TYPE       Set Accept header (default: application/json)"
    echo "  -v, --verbose           Show request details"
    echo "  -s, --save FILE         Save response to file"
    echo ""
    echo -e "${BLUE}Environment Variables:${NC}"
    echo "  API_BASE_URL            Default base URL"
    echo "  API_TOKEN               Default bearer token"
    exit 0
}

# Parse arguments
if [ $# -lt 2 ]; then
    usage
fi

METHOD=$1
ROUTE=$2
DATA=""
TOKEN="${API_TOKEN:-}"
VERBOSE=false
SAVE_FILE=""

shift 2

# Check if third argument is data (not starting with -)
if [ $# -gt 0 ] && [[ ! "$1" =~ ^- ]]; then
    DATA="$1"
    shift
fi

# Parse options
while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            usage
            ;;
        -b|--base-url)
            BASE_URL="$2"
            shift 2
            ;;
        -t|--token)
            TOKEN="$2"
            shift 2
            ;;
        -c|--content-type)
            CONTENT_TYPE="$2"
            shift 2
            ;;
        -a|--accept)
            ACCEPT="$2"
            shift 2
            ;;
        -v|--verbose)
            VERBOSE=true
            shift
            ;;
        -s|--save)
            SAVE_FILE="$2"
            shift 2
            ;;
        *)
            echo -e "${RED}Error: Unknown option $1${NC}"
            usage
            ;;
    esac
done

# Build URL
URL="${BASE_URL}${ROUTE}"

# Show request details if verbose
if [ "$VERBOSE" = true ]; then
    echo -e "${YELLOW}=== REQUEST DETAILS ===${NC}"
    echo -e "${BLUE}Method:${NC} $METHOD"
    echo -e "${BLUE}URL:${NC} $URL"
    echo -e "${BLUE}Content-Type:${NC} $CONTENT_TYPE"
    echo -e "${BLUE}Accept:${NC} $ACCEPT"
    if [ -n "$TOKEN" ]; then
        echo -e "${BLUE}Authorization:${NC} Bearer ***${TOKEN: -8}"
    fi
    if [ -n "$DATA" ]; then
        echo -e "${BLUE}Data:${NC} $DATA"
    fi
    echo ""
fi

# Build curl command
CURL_CMD="curl -X $METHOD"
CURL_CMD="$CURL_CMD -H 'Content-Type: $CONTENT_TYPE'"
CURL_CMD="$CURL_CMD -H 'Accept: $ACCEPT'"

if [ -n "$TOKEN" ]; then
    CURL_CMD="$CURL_CMD -H 'Authorization: Bearer $TOKEN'"
fi

if [ -n "$DATA" ]; then
    CURL_CMD="$CURL_CMD -d '$DATA'"
fi

CURL_CMD="$CURL_CMD '$URL'"

# Add pretty printing if jq is available
if command -v jq &> /dev/null; then
    CURL_CMD="$CURL_CMD -s -w '\n\nHTTP Status: %{http_code}\n' | jq -C"
else
    CURL_CMD="$CURL_CMD -w '\n\nHTTP Status: %{http_code}\n'"
fi

# Execute request
echo -e "${YELLOW}=== RESPONSE ===${NC}"
RESPONSE=$(eval $CURL_CMD)
echo "$RESPONSE"

# Save to file if requested
if [ -n "$SAVE_FILE" ]; then
    echo "$RESPONSE" > "$SAVE_FILE"
    echo -e "\n${GREEN}Response saved to: $SAVE_FILE${NC}"
fi

# Check if response contains error
if echo "$RESPONSE" | grep -q '"error"'; then
    echo -e "\n${RED}⚠ Response contains errors${NC}"
    exit 1
else
    echo -e "\n${GREEN}✓ Request completed${NC}"
fi
