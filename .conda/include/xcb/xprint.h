/*
 * This file generated automatically from xprint.xml by c_client.py.
 * Edit at your peril.
 */

/**
 * @defgroup XCB_XPrint_API XCB XPrint API
 * @brief XPrint XCB Protocol Implementation.
 * @{
 **/

#ifndef __XPRINT_H
#define __XPRINT_H

#include "xcb.h"
#include "xproto.h"

#ifdef __cplusplus
extern "C" {
#endif

#define XCB_XPRINT_MAJOR_VERSION 1
#define XCB_XPRINT_MINOR_VERSION 0

extern xcb_extension_t xcb_x_print_id;

typedef char xcb_x_print_string8_t;

/**
 * @brief xcb_x_print_string8_iterator_t
 **/
typedef struct xcb_x_print_string8_iterator_t {
    xcb_x_print_string8_t *data;
    int                    rem;
    int                    index;
} xcb_x_print_string8_iterator_t;

/**
 * @brief xcb_x_print_printer_t
 **/
typedef struct xcb_x_print_printer_t {
    uint32_t nameLen;
    uint32_t descLen;
} xcb_x_print_printer_t;

/**
 * @brief xcb_x_print_printer_iterator_t
 **/
typedef struct xcb_x_print_printer_iterator_t {
    xcb_x_print_printer_t *data;
    int                    rem;
    int                    index;
} xcb_x_print_printer_iterator_t;

typedef uint32_t xcb_x_print_pcontext_t;

/**
 * @brief xcb_x_print_pcontext_iterator_t
 **/
typedef struct xcb_x_print_pcontext_iterator_t {
    xcb_x_print_pcontext_t *data;
    int                     rem;
    int                     index;
} xcb_x_print_pcontext_iterator_t;

typedef enum xcb_x_print_get_doc_t {
    XCB_X_PRINT_GET_DOC_FINISHED = 0,
    XCB_X_PRINT_GET_DOC_SECOND_CONSUMER = 1
} xcb_x_print_get_doc_t;

typedef enum xcb_x_print_ev_mask_t {
    XCB_X_PRINT_EV_MASK_NO_EVENT_MASK = 0,
    XCB_X_PRINT_EV_MASK_PRINT_MASK = 1,
    XCB_X_PRINT_EV_MASK_ATTRIBUTE_MASK = 2
} xcb_x_print_ev_mask_t;

typedef enum xcb_x_print_detail_t {
    XCB_X_PRINT_DETAIL_START_JOB_NOTIFY = 1,
    XCB_X_PRINT_DETAIL_END_JOB_NOTIFY = 2,
    XCB_X_PRINT_DETAIL_START_DOC_NOTIFY = 3,
    XCB_X_PRINT_DETAIL_END_DOC_NOTIFY = 4,
    XCB_X_PRINT_DETAIL_START_PAGE_NOTIFY = 5,
    XCB_X_PRINT_DETAIL_END_PAGE_NOTIFY = 6
} xcb_x_print_detail_t;

typedef enum xcb_x_print_attr_t {
    XCB_X_PRINT_ATTR_JOB_ATTR = 1,
    XCB_X_PRINT_ATTR_DOC_ATTR = 2,
    XCB_X_PRINT_ATTR_PAGE_ATTR = 3,
    XCB_X_PRINT_ATTR_PRINTER_ATTR = 4,
    XCB_X_PRINT_ATTR_SERVER_ATTR = 5,
    XCB_X_PRINT_ATTR_MEDIUM_ATTR = 6,
    XCB_X_PRINT_ATTR_SPOOLER_ATTR = 7
} xcb_x_print_attr_t;

/**
 * @brief xcb_x_print_print_query_version_cookie_t
 **/
typedef struct xcb_x_print_print_query_version_cookie_t {
    unsigned int sequence;
} xcb_x_print_print_query_version_cookie_t;

/** Opcode for xcb_x_print_print_query_version. */
#define XCB_X_PRINT_PRINT_QUERY_VERSION 0

/**
 * @brief xcb_x_print_print_query_version_request_t
 **/
typedef struct xcb_x_print_print_query_version_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
} xcb_x_print_print_query_version_request_t;

/**
 * @brief xcb_x_print_print_query_version_reply_t
 **/
typedef struct xcb_x_print_print_query_version_reply_t {
    uint8_t  response_type;
    uint8_t  pad0;
    uint16_t sequence;
    uint32_t length;
    uint16_t major_version;
    uint16_t minor_version;
} xcb_x_print_print_query_version_reply_t;

/**
 * @brief xcb_x_print_print_get_printer_list_cookie_t
 **/
typedef struct xcb_x_print_print_get_printer_list_cookie_t {
    unsigned int sequence;
} xcb_x_print_print_get_printer_list_cookie_t;

/** Opcode for xcb_x_print_print_get_printer_list. */
#define XCB_X_PRINT_PRINT_GET_PRINTER_LIST 1

/**
 * @brief xcb_x_print_print_get_printer_list_request_t
 **/
typedef struct xcb_x_print_print_get_printer_list_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
    uint32_t printerNameLen;
    uint32_t localeLen;
} xcb_x_print_print_get_printer_list_request_t;

/**
 * @brief xcb_x_print_print_get_printer_list_reply_t
 **/
typedef struct xcb_x_print_print_get_printer_list_reply_t {
    uint8_t  response_type;
    uint8_t  pad0;
    uint16_t sequence;
    uint32_t length;
    uint32_t listCount;
    uint8_t  pad1[20];
} xcb_x_print_print_get_printer_list_reply_t;

/** Opcode for xcb_x_print_print_rehash_printer_list. */
#define XCB_X_PRINT_PRINT_REHASH_PRINTER_LIST 20

/**
 * @brief xcb_x_print_print_rehash_printer_list_request_t
 **/
typedef struct xcb_x_print_print_rehash_printer_list_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
} xcb_x_print_print_rehash_printer_list_request_t;

/** Opcode for xcb_x_print_create_context. */
#define XCB_X_PRINT_CREATE_CONTEXT 2

/**
 * @brief xcb_x_print_create_context_request_t
 **/
typedef struct xcb_x_print_create_context_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
    uint32_t context_id;
    uint32_t printerNameLen;
    uint32_t localeLen;
} xcb_x_print_create_context_request_t;

/** Opcode for xcb_x_print_print_set_context. */
#define XCB_X_PRINT_PRINT_SET_CONTEXT 3

/**
 * @brief xcb_x_print_print_set_context_request_t
 **/
typedef struct xcb_x_print_print_set_context_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
    uint32_t context;
} xcb_x_print_print_set_context_request_t;

/**
 * @brief xcb_x_print_print_get_context_cookie_t
 **/
typedef struct xcb_x_print_print_get_context_cookie_t {
    unsigned int sequence;
} xcb_x_print_print_get_context_cookie_t;

/** Opcode for xcb_x_print_print_get_context. */
#define XCB_X_PRINT_PRINT_GET_CONTEXT 4

/**
 * @brief xcb_x_print_print_get_context_request_t
 **/
typedef struct xcb_x_print_print_get_context_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
} xcb_x_print_print_get_context_request_t;

/**
 * @brief xcb_x_print_print_get_context_reply_t
 **/
typedef struct xcb_x_print_print_get_context_reply_t {
    uint8_t  response_type;
    uint8_t  pad0;
    uint16_t sequence;
    uint32_t length;
    uint32_t context;
} xcb_x_print_print_get_context_reply_t;

/** Opcode for xcb_x_print_print_destroy_context. */
#define XCB_X_PRINT_PRINT_DESTROY_CONTEXT 5

/**
 * @brief xcb_x_print_print_destroy_context_request_t
 **/
typedef struct xcb_x_print_print_destroy_context_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
    uint32_t context;
} xcb_x_print_print_destroy_context_request_t;

/**
 * @brief xcb_x_print_print_get_screen_of_context_cookie_t
 **/
typedef struct xcb_x_print_print_get_screen_of_context_cookie_t {
    unsigned int sequence;
} xcb_x_print_print_get_screen_of_context_cookie_t;

/** Opcode for xcb_x_print_print_get_screen_of_context. */
#define XCB_X_PRINT_PRINT_GET_SCREEN_OF_CONTEXT 6

/**
 * @brief xcb_x_print_print_get_screen_of_context_request_t
 **/
typedef struct xcb_x_print_print_get_screen_of_context_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
} xcb_x_print_print_get_screen_of_context_request_t;

/**
 * @brief xcb_x_print_print_get_screen_of_context_reply_t
 **/
typedef struct xcb_x_print_print_get_screen_of_context_reply_t {
    uint8_t      response_type;
    uint8_t      pad0;
    uint16_t     sequence;
    uint32_t     length;
    xcb_window_t root;
} xcb_x_print_print_get_screen_of_context_reply_t;

/** Opcode for xcb_x_print_print_start_job. */
#define XCB_X_PRINT_PRINT_START_JOB 7

/**
 * @brief xcb_x_print_print_start_job_request_t
 **/
typedef struct xcb_x_print_print_start_job_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
    uint8_t  output_mode;
} xcb_x_print_print_start_job_request_t;

/** Opcode for xcb_x_print_print_end_job. */
#define XCB_X_PRINT_PRINT_END_JOB 8

/**
 * @brief xcb_x_print_print_end_job_request_t
 **/
typedef struct xcb_x_print_print_end_job_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
    uint8_t  cancel;
} xcb_x_print_print_end_job_request_t;

/** Opcode for xcb_x_print_print_start_doc. */
#define XCB_X_PRINT_PRINT_START_DOC 9

/**
 * @brief xcb_x_print_print_start_doc_request_t
 **/
typedef struct xcb_x_print_print_start_doc_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
    uint8_t  driver_mode;
} xcb_x_print_print_start_doc_request_t;

/** Opcode for xcb_x_print_print_end_doc. */
#define XCB_X_PRINT_PRINT_END_DOC 10

/**
 * @brief xcb_x_print_print_end_doc_request_t
 **/
typedef struct xcb_x_print_print_end_doc_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
    uint8_t  cancel;
} xcb_x_print_print_end_doc_request_t;

/** Opcode for xcb_x_print_print_put_document_data. */
#define XCB_X_PRINT_PRINT_PUT_DOCUMENT_DATA 11

/**
 * @brief xcb_x_print_print_put_document_data_request_t
 **/
typedef struct xcb_x_print_print_put_document_data_request_t {
    uint8_t        major_opcode;
    uint8_t        minor_opcode;
    uint16_t       length;
    xcb_drawable_t drawable;
    uint32_t       len_data;
    uint16_t       len_fmt;
    uint16_t       len_options;
} xcb_x_print_print_put_document_data_request_t;

/**
 * @brief xcb_x_print_print_get_document_data_cookie_t
 **/
typedef struct xcb_x_print_print_get_document_data_cookie_t {
    unsigned int sequence;
} xcb_x_print_print_get_document_data_cookie_t;

/** Opcode for xcb_x_print_print_get_document_data. */
#define XCB_X_PRINT_PRINT_GET_DOCUMENT_DATA 12

/**
 * @brief xcb_x_print_print_get_document_data_request_t
 **/
typedef struct xcb_x_print_print_get_document_data_request_t {
    uint8_t                major_opcode;
    uint8_t                minor_opcode;
    uint16_t               length;
    xcb_x_print_pcontext_t context;
    uint32_t               max_bytes;
} xcb_x_print_print_get_document_data_request_t;

/**
 * @brief xcb_x_print_print_get_document_data_reply_t
 **/
typedef struct xcb_x_print_print_get_document_data_reply_t {
    uint8_t  response_type;
    uint8_t  pad0;
    uint16_t sequence;
    uint32_t length;
    uint32_t status_code;
    uint32_t finished_flag;
    uint32_t dataLen;
    uint8_t  pad1[12];
} xcb_x_print_print_get_document_data_reply_t;

/** Opcode for xcb_x_print_print_start_page. */
#define XCB_X_PRINT_PRINT_START_PAGE 13

/**
 * @brief xcb_x_print_print_start_page_request_t
 **/
typedef struct xcb_x_print_print_start_page_request_t {
    uint8_t      major_opcode;
    uint8_t      minor_opcode;
    uint16_t     length;
    xcb_window_t window;
} xcb_x_print_print_start_page_request_t;

/** Opcode for xcb_x_print_print_end_page. */
#define XCB_X_PRINT_PRINT_END_PAGE 14

/**
 * @brief xcb_x_print_print_end_page_request_t
 **/
typedef struct xcb_x_print_print_end_page_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
    uint8_t  cancel;
    uint8_t  pad0[3];
} xcb_x_print_print_end_page_request_t;

/** Opcode for xcb_x_print_print_select_input. */
#define XCB_X_PRINT_PRINT_SELECT_INPUT 15

/**
 * @brief xcb_x_print_print_select_input_request_t
 **/
typedef struct xcb_x_print_print_select_input_request_t {
    uint8_t                major_opcode;
    uint8_t                minor_opcode;
    uint16_t               length;
    xcb_x_print_pcontext_t context;
    uint32_t               event_mask;
} xcb_x_print_print_select_input_request_t;

/**
 * @brief xcb_x_print_print_input_selected_cookie_t
 **/
typedef struct xcb_x_print_print_input_selected_cookie_t {
    unsigned int sequence;
} xcb_x_print_print_input_selected_cookie_t;

/** Opcode for xcb_x_print_print_input_selected. */
#define XCB_X_PRINT_PRINT_INPUT_SELECTED 16

/**
 * @brief xcb_x_print_print_input_selected_request_t
 **/
typedef struct xcb_x_print_print_input_selected_request_t {
    uint8_t                major_opcode;
    uint8_t                minor_opcode;
    uint16_t               length;
    xcb_x_print_pcontext_t context;
} xcb_x_print_print_input_selected_request_t;

/**
 * @brief xcb_x_print_print_input_selected_reply_t
 **/
typedef struct xcb_x_print_print_input_selected_reply_t {
    uint8_t  response_type;
    uint8_t  pad0;
    uint16_t sequence;
    uint32_t length;
    uint32_t event_mask;
    uint32_t all_events_mask;
} xcb_x_print_print_input_selected_reply_t;

/**
 * @brief xcb_x_print_print_get_attributes_cookie_t
 **/
typedef struct xcb_x_print_print_get_attributes_cookie_t {
    unsigned int sequence;
} xcb_x_print_print_get_attributes_cookie_t;

/** Opcode for xcb_x_print_print_get_attributes. */
#define XCB_X_PRINT_PRINT_GET_ATTRIBUTES 17

/**
 * @brief xcb_x_print_print_get_attributes_request_t
 **/
typedef struct xcb_x_print_print_get_attributes_request_t {
    uint8_t                major_opcode;
    uint8_t                minor_opcode;
    uint16_t               length;
    xcb_x_print_pcontext_t context;
    uint8_t                pool;
    uint8_t                pad0[3];
} xcb_x_print_print_get_attributes_request_t;

/**
 * @brief xcb_x_print_print_get_attributes_reply_t
 **/
typedef struct xcb_x_print_print_get_attributes_reply_t {
    uint8_t  response_type;
    uint8_t  pad0;
    uint16_t sequence;
    uint32_t length;
    uint32_t stringLen;
    uint8_t  pad1[20];
} xcb_x_print_print_get_attributes_reply_t;

/**
 * @brief xcb_x_print_print_get_one_attributes_cookie_t
 **/
typedef struct xcb_x_print_print_get_one_attributes_cookie_t {
    unsigned int sequence;
} xcb_x_print_print_get_one_attributes_cookie_t;

/** Opcode for xcb_x_print_print_get_one_attributes. */
#define XCB_X_PRINT_PRINT_GET_ONE_ATTRIBUTES 19

/**
 * @brief xcb_x_print_print_get_one_attributes_request_t
 **/
typedef struct xcb_x_print_print_get_one_attributes_request_t {
    uint8_t                major_opcode;
    uint8_t                minor_opcode;
    uint16_t               length;
    xcb_x_print_pcontext_t context;
    uint32_t               nameLen;
    uint8_t                pool;
    uint8_t                pad0[3];
} xcb_x_print_print_get_one_attributes_request_t;

/**
 * @brief xcb_x_print_print_get_one_attributes_reply_t
 **/
typedef struct xcb_x_print_print_get_one_attributes_reply_t {
    uint8_t  response_type;
    uint8_t  pad0;
    uint16_t sequence;
    uint32_t length;
    uint32_t valueLen;
    uint8_t  pad1[20];
} xcb_x_print_print_get_one_attributes_reply_t;

/** Opcode for xcb_x_print_print_set_attributes. */
#define XCB_X_PRINT_PRINT_SET_ATTRIBUTES 18

/**
 * @brief xcb_x_print_print_set_attributes_request_t
 **/
typedef struct xcb_x_print_print_set_attributes_request_t {
    uint8_t                major_opcode;
    uint8_t                minor_opcode;
    uint16_t               length;
    xcb_x_print_pcontext_t context;
    uint32_t               stringLen;
    uint8_t                pool;
    uint8_t                rule;
    uint8_t                pad0[2];
} xcb_x_print_print_set_attributes_request_t;

/**
 * @brief xcb_x_print_print_get_page_dimensions_cookie_t
 **/
typedef struct xcb_x_print_print_get_page_dimensions_cookie_t {
    unsigned int sequence;
} xcb_x_print_print_get_page_dimensions_cookie_t;

/** Opcode for xcb_x_print_print_get_page_dimensions. */
#define XCB_X_PRINT_PRINT_GET_PAGE_DIMENSIONS 21

/**
 * @brief xcb_x_print_print_get_page_dimensions_request_t
 **/
typedef struct xcb_x_print_print_get_page_dimensions_request_t {
    uint8_t                major_opcode;
    uint8_t                minor_opcode;
    uint16_t               length;
    xcb_x_print_pcontext_t context;
} xcb_x_print_print_get_page_dimensions_request_t;

/**
 * @brief xcb_x_print_print_get_page_dimensions_reply_t
 **/
typedef struct xcb_x_print_print_get_page_dimensions_reply_t {
    uint8_t  response_type;
    uint8_t  pad0;
    uint16_t sequence;
    uint32_t length;
    uint16_t width;
    uint16_t height;
    uint16_t offset_x;
    uint16_t offset_y;
    uint16_t reproducible_width;
    uint16_t reproducible_height;
} xcb_x_print_print_get_page_dimensions_reply_t;

/**
 * @brief xcb_x_print_print_query_screens_cookie_t
 **/
typedef struct xcb_x_print_print_query_screens_cookie_t {
    unsigned int sequence;
} xcb_x_print_print_query_screens_cookie_t;

/** Opcode for xcb_x_print_print_query_screens. */
#define XCB_X_PRINT_PRINT_QUERY_SCREENS 22

/**
 * @brief xcb_x_print_print_query_screens_request_t
 **/
typedef struct xcb_x_print_print_query_screens_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
} xcb_x_print_print_query_screens_request_t;

/**
 * @brief xcb_x_print_print_query_screens_reply_t
 **/
typedef struct xcb_x_print_print_query_screens_reply_t {
    uint8_t  response_type;
    uint8_t  pad0;
    uint16_t sequence;
    uint32_t length;
    uint32_t listCount;
    uint8_t  pad1[20];
} xcb_x_print_print_query_screens_reply_t;

/**
 * @brief xcb_x_print_print_set_image_resolution_cookie_t
 **/
typedef struct xcb_x_print_print_set_image_resolution_cookie_t {
    unsigned int sequence;
} xcb_x_print_print_set_image_resolution_cookie_t;

/** Opcode for xcb_x_print_print_set_image_resolution. */
#define XCB_X_PRINT_PRINT_SET_IMAGE_RESOLUTION 23

/**
 * @brief xcb_x_print_print_set_image_resolution_request_t
 **/
typedef struct xcb_x_print_print_set_image_resolution_request_t {
    uint8_t                major_opcode;
    uint8_t                minor_opcode;
    uint16_t               length;
    xcb_x_print_pcontext_t context;
    uint16_t               image_resolution;
} xcb_x_print_print_set_image_resolution_request_t;

/**
 * @brief xcb_x_print_print_set_image_resolution_reply_t
 **/
typedef struct xcb_x_print_print_set_image_resolution_reply_t {
    uint8_t  response_type;
    uint8_t  status;
    uint16_t sequence;
    uint32_t length;
    uint16_t previous_resolutions;
} xcb_x_print_print_set_image_resolution_reply_t;

/**
 * @brief xcb_x_print_print_get_image_resolution_cookie_t
 **/
typedef struct xcb_x_print_print_get_image_resolution_cookie_t {
    unsigned int sequence;
} xcb_x_print_print_get_image_resolution_cookie_t;

/** Opcode for xcb_x_print_print_get_image_resolution. */
#define XCB_X_PRINT_PRINT_GET_IMAGE_RESOLUTION 24

/**
 * @brief xcb_x_print_print_get_image_resolution_request_t
 **/
typedef struct xcb_x_print_print_get_image_resolution_request_t {
    uint8_t                major_opcode;
    uint8_t                minor_opcode;
    uint16_t               length;
    xcb_x_print_pcontext_t context;
} xcb_x_print_print_get_image_resolution_request_t;

/**
 * @brief xcb_x_print_print_get_image_resolution_reply_t
 **/
typedef struct xcb_x_print_print_get_image_resolution_reply_t {
    uint8_t  response_type;
    uint8_t  pad0;
    uint16_t sequence;
    uint32_t length;
    uint16_t image_resolution;
} xcb_x_print_print_get_image_resolution_reply_t;

/** Opcode for xcb_x_print_notify. */
#define XCB_X_PRINT_NOTIFY 0

/**
 * @brief xcb_x_print_notify_event_t
 **/
typedef struct xcb_x_print_notify_event_t {
    uint8_t                response_type;
    uint8_t                detail;
    uint16_t               sequence;
    xcb_x_print_pcontext_t context;
    uint8_t                cancel;
} xcb_x_print_notify_event_t;

/** Opcode for xcb_x_print_attribut_notify. */
#define XCB_X_PRINT_ATTRIBUT_NOTIFY 1

/**
 * @brief xcb_x_print_attribut_notify_event_t
 **/
typedef struct xcb_x_print_attribut_notify_event_t {
    uint8_t                response_type;
    uint8_t                detail;
    uint16_t               sequence;
    xcb_x_print_pcontext_t context;
} xcb_x_print_attribut_notify_event_t;

/** Opcode for xcb_x_print_bad_context. */
#define XCB_X_PRINT_BAD_CONTEXT 0

/**
 * @brief xcb_x_print_bad_context_error_t
 **/
typedef struct xcb_x_print_bad_context_error_t {
    uint8_t  response_type;
    uint8_t  error_code;
    uint16_t sequence;
    uint32_t bad_value;
    uint16_t minor_opcode;
    uint8_t  major_opcode;
} xcb_x_print_bad_context_error_t;

/** Opcode for xcb_x_print_bad_sequence. */
#define XCB_X_PRINT_BAD_SEQUENCE 1

/**
 * @brief xcb_x_print_bad_sequence_error_t
 **/
typedef struct xcb_x_print_bad_sequence_error_t {
    uint8_t  response_type;
    uint8_t  error_code;
    uint16_t sequence;
    uint32_t bad_value;
    uint16_t minor_opcode;
    uint8_t  major_opcode;
} xcb_x_print_bad_sequence_error_t;

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_x_print_string8_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_x_print_string8_t)
 */
void
xcb_x_print_string8_next (xcb_x_print_string8_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_x_print_string8_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_x_print_string8_end (xcb_x_print_string8_iterator_t i);

int
xcb_x_print_printer_serialize (void                        **_buffer,
                               const xcb_x_print_printer_t  *_aux,
                               const xcb_x_print_string8_t  *name,
                               const xcb_x_print_string8_t  *description);

int
xcb_x_print_printer_unserialize (const void              *_buffer,
                                 xcb_x_print_printer_t  **_aux);

int
xcb_x_print_printer_sizeof (const void  *_buffer);

xcb_x_print_string8_t *
xcb_x_print_printer_name (const xcb_x_print_printer_t *R);

int
xcb_x_print_printer_name_length (const xcb_x_print_printer_t *R);

xcb_generic_iterator_t
xcb_x_print_printer_name_end (const xcb_x_print_printer_t *R);

xcb_x_print_string8_t *
xcb_x_print_printer_description (const xcb_x_print_printer_t *R);

int
xcb_x_print_printer_description_length (const xcb_x_print_printer_t *R);

xcb_generic_iterator_t
xcb_x_print_printer_description_end (const xcb_x_print_printer_t *R);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_x_print_printer_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_x_print_printer_t)
 */
void
xcb_x_print_printer_next (xcb_x_print_printer_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_x_print_printer_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_x_print_printer_end (xcb_x_print_printer_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_x_print_pcontext_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_x_print_pcontext_t)
 */
void
xcb_x_print_pcontext_next (xcb_x_print_pcontext_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_x_print_pcontext_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_x_print_pcontext_end (xcb_x_print_pcontext_iterator_t i);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_x_print_print_query_version_cookie_t
xcb_x_print_print_query_version (xcb_connection_t *c);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will cause
 * a reply to be generated. Any returned error will be
 * placed in the event queue.
 */
xcb_x_print_print_query_version_cookie_t
xcb_x_print_print_query_version_unchecked (xcb_connection_t *c);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_x_print_print_query_version_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_x_print_print_query_version_reply_t *
xcb_x_print_print_query_version_reply (xcb_connection_t                          *c,
                                       xcb_x_print_print_query_version_cookie_t   cookie  /**< */,
                                       xcb_generic_error_t                      **e);

int
xcb_x_print_print_get_printer_list_sizeof (const void  *_buffer);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_x_print_print_get_printer_list_cookie_t
xcb_x_print_print_get_printer_list (xcb_connection_t            *c,
                                    uint32_t                     printerNameLen,
                                    uint32_t                     localeLen,
                                    const xcb_x_print_string8_t *printer_name,
                                    const xcb_x_print_string8_t *locale);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will cause
 * a reply to be generated. Any returned error will be
 * placed in the event queue.
 */
xcb_x_print_print_get_printer_list_cookie_t
xcb_x_print_print_get_printer_list_unchecked (xcb_connection_t            *c,
                                              uint32_t                     printerNameLen,
                                              uint32_t                     localeLen,
                                              const xcb_x_print_string8_t *printer_name,
                                              const xcb_x_print_string8_t *locale);

int
xcb_x_print_print_get_printer_list_printers_length (const xcb_x_print_print_get_printer_list_reply_t *R);

xcb_x_print_printer_iterator_t
xcb_x_print_print_get_printer_list_printers_iterator (const xcb_x_print_print_get_printer_list_reply_t *R);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_x_print_print_get_printer_list_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_x_print_print_get_printer_list_reply_t *
xcb_x_print_print_get_printer_list_reply (xcb_connection_t                             *c,
                                          xcb_x_print_print_get_printer_list_cookie_t   cookie  /**< */,
                                          xcb_generic_error_t                         **e);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will not cause
 * a reply to be generated. Any returned error will be
 * saved for handling by xcb_request_check().
 */
xcb_void_cookie_t
xcb_x_print_print_rehash_printer_list_checked (xcb_connection_t *c);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_void_cookie_t
xcb_x_print_print_rehash_printer_list (xcb_connection_t *c);

int
xcb_x_print_create_context_sizeof (const void  *_buffer);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will not cause
 * a reply to be generated. Any returned error will be
 * saved for handling by xcb_request_check().
 */
xcb_void_cookie_t
xcb_x_print_create_context_checked (xcb_connection_t            *c,
                                    uint32_t                     context_id,
                                    uint32_t                     printerNameLen,
                                    uint32_t                     localeLen,
                                    const xcb_x_print_string8_t *printerName,
                                    const xcb_x_print_string8_t *locale);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_void_cookie_t
xcb_x_print_create_context (xcb_connection_t            *c,
                            uint32_t                     context_id,
                            uint32_t                     printerNameLen,
                            uint32_t                     localeLen,
                            const xcb_x_print_string8_t *printerName,
                            const xcb_x_print_string8_t *locale);

xcb_x_print_string8_t *
xcb_x_print_create_context_printer_name (const xcb_x_print_create_context_request_t *R);

int
xcb_x_print_create_context_printer_name_length (const xcb_x_print_create_context_request_t *R);

xcb_generic_iterator_t
xcb_x_print_create_context_printer_name_end (const xcb_x_print_create_context_request_t *R);

xcb_x_print_string8_t *
xcb_x_print_create_context_locale (const xcb_x_print_create_context_request_t *R);

int
xcb_x_print_create_context_locale_length (const xcb_x_print_create_context_request_t *R);

xcb_generic_iterator_t
xcb_x_print_create_context_locale_end (const xcb_x_print_create_context_request_t *R);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will not cause
 * a reply to be generated. Any returned error will be
 * saved for handling by xcb_request_check().
 */
xcb_void_cookie_t
xcb_x_print_print_set_context_checked (xcb_connection_t *c,
                                       uint32_t          context);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_void_cookie_t
xcb_x_print_print_set_context (xcb_connection_t *c,
                               uint32_t          context);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_x_print_print_get_context_cookie_t
xcb_x_print_print_get_context (xcb_connection_t *c);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will cause
 * a reply to be generated. Any returned error will be
 * placed in the event queue.
 */
xcb_x_print_print_get_context_cookie_t
xcb_x_print_print_get_context_unchecked (xcb_connection_t *c);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_x_print_print_get_context_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_x_print_print_get_context_reply_t *
xcb_x_print_print_get_context_reply (xcb_connection_t                        *c,
                                     xcb_x_print_print_get_context_cookie_t   cookie  /**< */,
                                     xcb_generic_error_t                    **e);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will not cause
 * a reply to be generated. Any returned error will be
 * saved for handling by xcb_request_check().
 */
xcb_void_cookie_t
xcb_x_print_print_destroy_context_checked (xcb_connection_t *c,
                                           uint32_t          context);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_void_cookie_t
xcb_x_print_print_destroy_context (xcb_connection_t *c,
                                   uint32_t          context);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_x_print_print_get_screen_of_context_cookie_t
xcb_x_print_print_get_screen_of_context (xcb_connection_t *c);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will cause
 * a reply to be generated. Any returned error will be
 * placed in the event queue.
 */
xcb_x_print_print_get_screen_of_context_cookie_t
xcb_x_print_print_get_screen_of_context_unchecked (xcb_connection_t *c);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_x_print_print_get_screen_of_context_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_x_print_print_get_screen_of_context_reply_t *
xcb_x_print_print_get_screen_of_context_reply (xcb_connection_t                                  *c,
                                               xcb_x_print_print_get_screen_of_context_cookie_t   cookie  /**< */,
                                               xcb_generic_error_t                              **e);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will not cause
 * a reply to be generated. Any returned error will be
 * saved for handling by xcb_request_check().
 */
xcb_void_cookie_t
xcb_x_print_print_start_job_checked (xcb_connection_t *c,
                                     uint8_t           output_mode);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_void_cookie_t
xcb_x_print_print_start_job (xcb_connection_t *c,
                             uint8_t           output_mode);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will not cause
 * a reply to be generated. Any returned error will be
 * saved for handling by xcb_request_check().
 */
xcb_void_cookie_t
xcb_x_print_print_end_job_checked (xcb_connection_t *c,
                                   uint8_t           cancel);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_void_cookie_t
xcb_x_print_print_end_job (xcb_connection_t *c,
                           uint8_t           cancel);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will not cause
 * a reply to be generated. Any returned error will be
 * saved for handling by xcb_request_check().
 */
xcb_void_cookie_t
xcb_x_print_print_start_doc_checked (xcb_connection_t *c,
                                     uint8_t           driver_mode);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_void_cookie_t
xcb_x_print_print_start_doc (xcb_connection_t *c,
                             uint8_t           driver_mode);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will not cause
 * a reply to be generated. Any returned error will be
 * saved for handling by xcb_request_check().
 */
xcb_void_cookie_t
xcb_x_print_print_end_doc_checked (xcb_connection_t *c,
                                   uint8_t           cancel);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_void_cookie_t
xcb_x_print_print_end_doc (xcb_connection_t *c,
                           uint8_t           cancel);

int
xcb_x_print_print_put_document_data_sizeof (const void  *_buffer);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will not cause
 * a reply to be generated. Any returned error will be
 * saved for handling by xcb_request_check().
 */
xcb_void_cookie_t
xcb_x_print_print_put_document_data_checked (xcb_connection_t            *c,
                                             xcb_drawable_t               drawable,
                                             uint32_t                     len_data,
                                             uint16_t                     len_fmt,
                                             uint16_t                     len_options,
                                             const uint8_t               *data,
                                             const xcb_x_print_string8_t *doc_format,
                                             const xcb_x_print_string8_t *options);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_void_cookie_t
xcb_x_print_print_put_document_data (xcb_connection_t            *c,
                                     xcb_drawable_t               drawable,
                                     uint32_t                     len_data,
                                     uint16_t                     len_fmt,
                                     uint16_t                     len_options,
                                     const uint8_t               *data,
                                     const xcb_x_print_string8_t *doc_format,
                                     const xcb_x_print_string8_t *options);

uint8_t *
xcb_x_print_print_put_document_data_data (const xcb_x_print_print_put_document_data_request_t *R);

int
xcb_x_print_print_put_document_data_data_length (const xcb_x_print_print_put_document_data_request_t *R);

xcb_generic_iterator_t
xcb_x_print_print_put_document_data_data_end (const xcb_x_print_print_put_document_data_request_t *R);

xcb_x_print_string8_t *
xcb_x_print_print_put_document_data_doc_format (const xcb_x_print_print_put_document_data_request_t *R);

int
xcb_x_print_print_put_document_data_doc_format_length (const xcb_x_print_print_put_document_data_request_t *R);

xcb_generic_iterator_t
xcb_x_print_print_put_document_data_doc_format_end (const xcb_x_print_print_put_document_data_request_t *R);

xcb_x_print_string8_t *
xcb_x_print_print_put_document_data_options (const xcb_x_print_print_put_document_data_request_t *R);

int
xcb_x_print_print_put_document_data_options_length (const xcb_x_print_print_put_document_data_request_t *R);

xcb_generic_iterator_t
xcb_x_print_print_put_document_data_options_end (const xcb_x_print_print_put_document_data_request_t *R);

int
xcb_x_print_print_get_document_data_sizeof (const void  *_buffer);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_x_print_print_get_document_data_cookie_t
xcb_x_print_print_get_document_data (xcb_connection_t       *c,
                                     xcb_x_print_pcontext_t  context,
                                     uint32_t                max_bytes);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will cause
 * a reply to be generated. Any returned error will be
 * placed in the event queue.
 */
xcb_x_print_print_get_document_data_cookie_t
xcb_x_print_print_get_document_data_unchecked (xcb_connection_t       *c,
                                               xcb_x_print_pcontext_t  context,
                                               uint32_t                max_bytes);

uint8_t *
xcb_x_print_print_get_document_data_data (const xcb_x_print_print_get_document_data_reply_t *R);

int
xcb_x_print_print_get_document_data_data_length (const xcb_x_print_print_get_document_data_reply_t *R);

xcb_generic_iterator_t
xcb_x_print_print_get_document_data_data_end (const xcb_x_print_print_get_document_data_reply_t *R);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_x_print_print_get_document_data_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_x_print_print_get_document_data_reply_t *
xcb_x_print_print_get_document_data_reply (xcb_connection_t                              *c,
                                           xcb_x_print_print_get_document_data_cookie_t   cookie  /**< */,
                                           xcb_generic_error_t                          **e);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will not cause
 * a reply to be generated. Any returned error will be
 * saved for handling by xcb_request_check().
 */
xcb_void_cookie_t
xcb_x_print_print_start_page_checked (xcb_connection_t *c,
                                      xcb_window_t      window);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_void_cookie_t
xcb_x_print_print_start_page (xcb_connection_t *c,
                              xcb_window_t      window);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will not cause
 * a reply to be generated. Any returned error will be
 * saved for handling by xcb_request_check().
 */
xcb_void_cookie_t
xcb_x_print_print_end_page_checked (xcb_connection_t *c,
                                    uint8_t           cancel);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_void_cookie_t
xcb_x_print_print_end_page (xcb_connection_t *c,
                            uint8_t           cancel);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will not cause
 * a reply to be generated. Any returned error will be
 * saved for handling by xcb_request_check().
 */
xcb_void_cookie_t
xcb_x_print_print_select_input_checked (xcb_connection_t       *c,
                                        xcb_x_print_pcontext_t  context,
                                        uint32_t                event_mask);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_void_cookie_t
xcb_x_print_print_select_input (xcb_connection_t       *c,
                                xcb_x_print_pcontext_t  context,
                                uint32_t                event_mask);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_x_print_print_input_selected_cookie_t
xcb_x_print_print_input_selected (xcb_connection_t       *c,
                                  xcb_x_print_pcontext_t  context);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will cause
 * a reply to be generated. Any returned error will be
 * placed in the event queue.
 */
xcb_x_print_print_input_selected_cookie_t
xcb_x_print_print_input_selected_unchecked (xcb_connection_t       *c,
                                            xcb_x_print_pcontext_t  context);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_x_print_print_input_selected_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_x_print_print_input_selected_reply_t *
xcb_x_print_print_input_selected_reply (xcb_connection_t                           *c,
                                        xcb_x_print_print_input_selected_cookie_t   cookie  /**< */,
                                        xcb_generic_error_t                       **e);

int
xcb_x_print_print_get_attributes_sizeof (const void  *_buffer);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_x_print_print_get_attributes_cookie_t
xcb_x_print_print_get_attributes (xcb_connection_t       *c,
                                  xcb_x_print_pcontext_t  context,
                                  uint8_t                 pool);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will cause
 * a reply to be generated. Any returned error will be
 * placed in the event queue.
 */
xcb_x_print_print_get_attributes_cookie_t
xcb_x_print_print_get_attributes_unchecked (xcb_connection_t       *c,
                                            xcb_x_print_pcontext_t  context,
                                            uint8_t                 pool);

xcb_x_print_string8_t *
xcb_x_print_print_get_attributes_attributes (const xcb_x_print_print_get_attributes_reply_t *R);

int
xcb_x_print_print_get_attributes_attributes_length (const xcb_x_print_print_get_attributes_reply_t *R);

xcb_generic_iterator_t
xcb_x_print_print_get_attributes_attributes_end (const xcb_x_print_print_get_attributes_reply_t *R);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_x_print_print_get_attributes_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_x_print_print_get_attributes_reply_t *
xcb_x_print_print_get_attributes_reply (xcb_connection_t                           *c,
                                        xcb_x_print_print_get_attributes_cookie_t   cookie  /**< */,
                                        xcb_generic_error_t                       **e);

int
xcb_x_print_print_get_one_attributes_sizeof (const void  *_buffer);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_x_print_print_get_one_attributes_cookie_t
xcb_x_print_print_get_one_attributes (xcb_connection_t            *c,
                                      xcb_x_print_pcontext_t       context,
                                      uint32_t                     nameLen,
                                      uint8_t                      pool,
                                      const xcb_x_print_string8_t *name);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will cause
 * a reply to be generated. Any returned error will be
 * placed in the event queue.
 */
xcb_x_print_print_get_one_attributes_cookie_t
xcb_x_print_print_get_one_attributes_unchecked (xcb_connection_t            *c,
                                                xcb_x_print_pcontext_t       context,
                                                uint32_t                     nameLen,
                                                uint8_t                      pool,
                                                const xcb_x_print_string8_t *name);

xcb_x_print_string8_t *
xcb_x_print_print_get_one_attributes_value (const xcb_x_print_print_get_one_attributes_reply_t *R);

int
xcb_x_print_print_get_one_attributes_value_length (const xcb_x_print_print_get_one_attributes_reply_t *R);

xcb_generic_iterator_t
xcb_x_print_print_get_one_attributes_value_end (const xcb_x_print_print_get_one_attributes_reply_t *R);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_x_print_print_get_one_attributes_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_x_print_print_get_one_attributes_reply_t *
xcb_x_print_print_get_one_attributes_reply (xcb_connection_t                               *c,
                                            xcb_x_print_print_get_one_attributes_cookie_t   cookie  /**< */,
                                            xcb_generic_error_t                           **e);

int
xcb_x_print_print_set_attributes_sizeof (const void  *_buffer,
                                         uint32_t     attributes_len);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will not cause
 * a reply to be generated. Any returned error will be
 * saved for handling by xcb_request_check().
 */
xcb_void_cookie_t
xcb_x_print_print_set_attributes_checked (xcb_connection_t            *c,
                                          xcb_x_print_pcontext_t       context,
                                          uint32_t                     stringLen,
                                          uint8_t                      pool,
                                          uint8_t                      rule,
                                          uint32_t                     attributes_len,
                                          const xcb_x_print_string8_t *attributes);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_void_cookie_t
xcb_x_print_print_set_attributes (xcb_connection_t            *c,
                                  xcb_x_print_pcontext_t       context,
                                  uint32_t                     stringLen,
                                  uint8_t                      pool,
                                  uint8_t                      rule,
                                  uint32_t                     attributes_len,
                                  const xcb_x_print_string8_t *attributes);

xcb_x_print_string8_t *
xcb_x_print_print_set_attributes_attributes (const xcb_x_print_print_set_attributes_request_t *R);

int
xcb_x_print_print_set_attributes_attributes_length (const xcb_x_print_print_set_attributes_request_t *R);

xcb_generic_iterator_t
xcb_x_print_print_set_attributes_attributes_end (const xcb_x_print_print_set_attributes_request_t *R);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_x_print_print_get_page_dimensions_cookie_t
xcb_x_print_print_get_page_dimensions (xcb_connection_t       *c,
                                       xcb_x_print_pcontext_t  context);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will cause
 * a reply to be generated. Any returned error will be
 * placed in the event queue.
 */
xcb_x_print_print_get_page_dimensions_cookie_t
xcb_x_print_print_get_page_dimensions_unchecked (xcb_connection_t       *c,
                                                 xcb_x_print_pcontext_t  context);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_x_print_print_get_page_dimensions_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_x_print_print_get_page_dimensions_reply_t *
xcb_x_print_print_get_page_dimensions_reply (xcb_connection_t                                *c,
                                             xcb_x_print_print_get_page_dimensions_cookie_t   cookie  /**< */,
                                             xcb_generic_error_t                            **e);

int
xcb_x_print_print_query_screens_sizeof (const void  *_buffer);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_x_print_print_query_screens_cookie_t
xcb_x_print_print_query_screens (xcb_connection_t *c);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will cause
 * a reply to be generated. Any returned error will be
 * placed in the event queue.
 */
xcb_x_print_print_query_screens_cookie_t
xcb_x_print_print_query_screens_unchecked (xcb_connection_t *c);

xcb_window_t *
xcb_x_print_print_query_screens_roots (const xcb_x_print_print_query_screens_reply_t *R);

int
xcb_x_print_print_query_screens_roots_length (const xcb_x_print_print_query_screens_reply_t *R);

xcb_generic_iterator_t
xcb_x_print_print_query_screens_roots_end (const xcb_x_print_print_query_screens_reply_t *R);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_x_print_print_query_screens_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_x_print_print_query_screens_reply_t *
xcb_x_print_print_query_screens_reply (xcb_connection_t                          *c,
                                       xcb_x_print_print_query_screens_cookie_t   cookie  /**< */,
                                       xcb_generic_error_t                      **e);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_x_print_print_set_image_resolution_cookie_t
xcb_x_print_print_set_image_resolution (xcb_connection_t       *c,
                                        xcb_x_print_pcontext_t  context,
                                        uint16_t                image_resolution);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will cause
 * a reply to be generated. Any returned error will be
 * placed in the event queue.
 */
xcb_x_print_print_set_image_resolution_cookie_t
xcb_x_print_print_set_image_resolution_unchecked (xcb_connection_t       *c,
                                                  xcb_x_print_pcontext_t  context,
                                                  uint16_t                image_resolution);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_x_print_print_set_image_resolution_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_x_print_print_set_image_resolution_reply_t *
xcb_x_print_print_set_image_resolution_reply (xcb_connection_t                                 *c,
                                              xcb_x_print_print_set_image_resolution_cookie_t   cookie  /**< */,
                                              xcb_generic_error_t                             **e);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_x_print_print_get_image_resolution_cookie_t
xcb_x_print_print_get_image_resolution (xcb_connection_t       *c,
                                        xcb_x_print_pcontext_t  context);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 * This form can be used only if the request will cause
 * a reply to be generated. Any returned error will be
 * placed in the event queue.
 */
xcb_x_print_print_get_image_resolution_cookie_t
xcb_x_print_print_get_image_resolution_unchecked (xcb_connection_t       *c,
                                                  xcb_x_print_pcontext_t  context);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_x_print_print_get_image_resolution_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_x_print_print_get_image_resolution_reply_t *
xcb_x_print_print_get_image_resolution_reply (xcb_connection_t                                 *c,
                                              xcb_x_print_print_get_image_resolution_cookie_t   cookie  /**< */,
                                              xcb_generic_error_t                             **e);


#ifdef __cplusplus
}
#endif

#endif

/**
 * @}
 */
