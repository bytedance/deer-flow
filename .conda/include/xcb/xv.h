/*
 * This file generated automatically from xv.xml by c_client.py.
 * Edit at your peril.
 */

/**
 * @defgroup XCB_Xv_API XCB Xv API
 * @brief Xv XCB Protocol Implementation.
 * @{
 **/

#ifndef __XV_H
#define __XV_H

#include "xcb.h"
#include "xproto.h"
#include "shm.h"

#ifdef __cplusplus
extern "C" {
#endif

#define XCB_XV_MAJOR_VERSION 2
#define XCB_XV_MINOR_VERSION 2

extern xcb_extension_t xcb_xv_id;

typedef uint32_t xcb_xv_port_t;

/**
 * @brief xcb_xv_port_iterator_t
 **/
typedef struct xcb_xv_port_iterator_t {
    xcb_xv_port_t *data;
    int            rem;
    int            index;
} xcb_xv_port_iterator_t;

typedef uint32_t xcb_xv_encoding_t;

/**
 * @brief xcb_xv_encoding_iterator_t
 **/
typedef struct xcb_xv_encoding_iterator_t {
    xcb_xv_encoding_t *data;
    int                rem;
    int                index;
} xcb_xv_encoding_iterator_t;

typedef enum xcb_xv_type_t {
    XCB_XV_TYPE_INPUT_MASK = 1,
    XCB_XV_TYPE_OUTPUT_MASK = 2,
    XCB_XV_TYPE_VIDEO_MASK = 4,
    XCB_XV_TYPE_STILL_MASK = 8,
    XCB_XV_TYPE_IMAGE_MASK = 16
} xcb_xv_type_t;

typedef enum xcb_xv_image_format_info_type_t {
    XCB_XV_IMAGE_FORMAT_INFO_TYPE_RGB = 0,
    XCB_XV_IMAGE_FORMAT_INFO_TYPE_YUV = 1
} xcb_xv_image_format_info_type_t;

typedef enum xcb_xv_image_format_info_format_t {
    XCB_XV_IMAGE_FORMAT_INFO_FORMAT_PACKED = 0,
    XCB_XV_IMAGE_FORMAT_INFO_FORMAT_PLANAR = 1
} xcb_xv_image_format_info_format_t;

typedef enum xcb_xv_attribute_flag_t {
    XCB_XV_ATTRIBUTE_FLAG_GETTABLE = 1,
    XCB_XV_ATTRIBUTE_FLAG_SETTABLE = 2
} xcb_xv_attribute_flag_t;

typedef enum xcb_xv_video_notify_reason_t {
    XCB_XV_VIDEO_NOTIFY_REASON_STARTED = 0,
    XCB_XV_VIDEO_NOTIFY_REASON_STOPPED = 1,
    XCB_XV_VIDEO_NOTIFY_REASON_BUSY = 2,
    XCB_XV_VIDEO_NOTIFY_REASON_PREEMPTED = 3,
    XCB_XV_VIDEO_NOTIFY_REASON_HARD_ERROR = 4
} xcb_xv_video_notify_reason_t;

typedef enum xcb_xv_scanline_order_t {
    XCB_XV_SCANLINE_ORDER_TOP_TO_BOTTOM = 0,
    XCB_XV_SCANLINE_ORDER_BOTTOM_TO_TOP = 1
} xcb_xv_scanline_order_t;

typedef enum xcb_xv_grab_port_status_t {
    XCB_XV_GRAB_PORT_STATUS_SUCCESS = 0,
    XCB_XV_GRAB_PORT_STATUS_BAD_EXTENSION = 1,
    XCB_XV_GRAB_PORT_STATUS_ALREADY_GRABBED = 2,
    XCB_XV_GRAB_PORT_STATUS_INVALID_TIME = 3,
    XCB_XV_GRAB_PORT_STATUS_BAD_REPLY = 4,
    XCB_XV_GRAB_PORT_STATUS_BAD_ALLOC = 5
} xcb_xv_grab_port_status_t;

/**
 * @brief xcb_xv_rational_t
 **/
typedef struct xcb_xv_rational_t {
    int32_t numerator;
    int32_t denominator;
} xcb_xv_rational_t;

/**
 * @brief xcb_xv_rational_iterator_t
 **/
typedef struct xcb_xv_rational_iterator_t {
    xcb_xv_rational_t *data;
    int                rem;
    int                index;
} xcb_xv_rational_iterator_t;

/**
 * @brief xcb_xv_format_t
 **/
typedef struct xcb_xv_format_t {
    xcb_visualid_t visual;
    uint8_t        depth;
    uint8_t        pad0[3];
} xcb_xv_format_t;

/**
 * @brief xcb_xv_format_iterator_t
 **/
typedef struct xcb_xv_format_iterator_t {
    xcb_xv_format_t *data;
    int              rem;
    int              index;
} xcb_xv_format_iterator_t;

/**
 * @brief xcb_xv_adaptor_info_t
 **/
typedef struct xcb_xv_adaptor_info_t {
    xcb_xv_port_t base_id;
    uint16_t      name_size;
    uint16_t      num_ports;
    uint16_t      num_formats;
    uint8_t       type;
    uint8_t       pad0;
} xcb_xv_adaptor_info_t;

/**
 * @brief xcb_xv_adaptor_info_iterator_t
 **/
typedef struct xcb_xv_adaptor_info_iterator_t {
    xcb_xv_adaptor_info_t *data;
    int                    rem;
    int                    index;
} xcb_xv_adaptor_info_iterator_t;

/**
 * @brief xcb_xv_encoding_info_t
 **/
typedef struct xcb_xv_encoding_info_t {
    xcb_xv_encoding_t encoding;
    uint16_t          name_size;
    uint16_t          width;
    uint16_t          height;
    uint8_t           pad0[2];
    xcb_xv_rational_t rate;
} xcb_xv_encoding_info_t;

/**
 * @brief xcb_xv_encoding_info_iterator_t
 **/
typedef struct xcb_xv_encoding_info_iterator_t {
    xcb_xv_encoding_info_t *data;
    int                     rem;
    int                     index;
} xcb_xv_encoding_info_iterator_t;

/**
 * @brief xcb_xv_image_t
 **/
typedef struct xcb_xv_image_t {
    uint32_t id;
    uint16_t width;
    uint16_t height;
    uint32_t data_size;
    uint32_t num_planes;
} xcb_xv_image_t;

/**
 * @brief xcb_xv_image_iterator_t
 **/
typedef struct xcb_xv_image_iterator_t {
    xcb_xv_image_t *data;
    int             rem;
    int             index;
} xcb_xv_image_iterator_t;

/**
 * @brief xcb_xv_attribute_info_t
 **/
typedef struct xcb_xv_attribute_info_t {
    uint32_t flags;
    int32_t  min;
    int32_t  max;
    uint32_t size;
} xcb_xv_attribute_info_t;

/**
 * @brief xcb_xv_attribute_info_iterator_t
 **/
typedef struct xcb_xv_attribute_info_iterator_t {
    xcb_xv_attribute_info_t *data;
    int                      rem;
    int                      index;
} xcb_xv_attribute_info_iterator_t;

/**
 * @brief xcb_xv_image_format_info_t
 **/
typedef struct xcb_xv_image_format_info_t {
    uint32_t id;
    uint8_t  type;
    uint8_t  byte_order;
    uint8_t  pad0[2];
    uint8_t  guid[16];
    uint8_t  bpp;
    uint8_t  num_planes;
    uint8_t  pad1[2];
    uint8_t  depth;
    uint8_t  pad2[3];
    uint32_t red_mask;
    uint32_t green_mask;
    uint32_t blue_mask;
    uint8_t  format;
    uint8_t  pad3[3];
    uint32_t y_sample_bits;
    uint32_t u_sample_bits;
    uint32_t v_sample_bits;
    uint32_t vhorz_y_period;
    uint32_t vhorz_u_period;
    uint32_t vhorz_v_period;
    uint32_t vvert_y_period;
    uint32_t vvert_u_period;
    uint32_t vvert_v_period;
    uint8_t  vcomp_order[32];
    uint8_t  vscanline_order;
    uint8_t  pad4[11];
} xcb_xv_image_format_info_t;

/**
 * @brief xcb_xv_image_format_info_iterator_t
 **/
typedef struct xcb_xv_image_format_info_iterator_t {
    xcb_xv_image_format_info_t *data;
    int                         rem;
    int                         index;
} xcb_xv_image_format_info_iterator_t;

/** Opcode for xcb_xv_bad_port. */
#define XCB_XV_BAD_PORT 0

/**
 * @brief xcb_xv_bad_port_error_t
 **/
typedef struct xcb_xv_bad_port_error_t {
    uint8_t  response_type;
    uint8_t  error_code;
    uint16_t sequence;
    uint32_t bad_value;
    uint16_t minor_opcode;
    uint8_t  major_opcode;
} xcb_xv_bad_port_error_t;

/** Opcode for xcb_xv_bad_encoding. */
#define XCB_XV_BAD_ENCODING 1

/**
 * @brief xcb_xv_bad_encoding_error_t
 **/
typedef struct xcb_xv_bad_encoding_error_t {
    uint8_t  response_type;
    uint8_t  error_code;
    uint16_t sequence;
    uint32_t bad_value;
    uint16_t minor_opcode;
    uint8_t  major_opcode;
} xcb_xv_bad_encoding_error_t;

/** Opcode for xcb_xv_bad_control. */
#define XCB_XV_BAD_CONTROL 2

/**
 * @brief xcb_xv_bad_control_error_t
 **/
typedef struct xcb_xv_bad_control_error_t {
    uint8_t  response_type;
    uint8_t  error_code;
    uint16_t sequence;
    uint32_t bad_value;
    uint16_t minor_opcode;
    uint8_t  major_opcode;
} xcb_xv_bad_control_error_t;

/** Opcode for xcb_xv_video_notify. */
#define XCB_XV_VIDEO_NOTIFY 0

/**
 * @brief xcb_xv_video_notify_event_t
 **/
typedef struct xcb_xv_video_notify_event_t {
    uint8_t         response_type;
    uint8_t         reason;
    uint16_t        sequence;
    xcb_timestamp_t time;
    xcb_drawable_t  drawable;
    xcb_xv_port_t   port;
} xcb_xv_video_notify_event_t;

/** Opcode for xcb_xv_port_notify. */
#define XCB_XV_PORT_NOTIFY 1

/**
 * @brief xcb_xv_port_notify_event_t
 **/
typedef struct xcb_xv_port_notify_event_t {
    uint8_t         response_type;
    uint8_t         pad0;
    uint16_t        sequence;
    xcb_timestamp_t time;
    xcb_xv_port_t   port;
    xcb_atom_t      attribute;
    int32_t         value;
} xcb_xv_port_notify_event_t;

/**
 * @brief xcb_xv_query_extension_cookie_t
 **/
typedef struct xcb_xv_query_extension_cookie_t {
    unsigned int sequence;
} xcb_xv_query_extension_cookie_t;

/** Opcode for xcb_xv_query_extension. */
#define XCB_XV_QUERY_EXTENSION 0

/**
 * @brief xcb_xv_query_extension_request_t
 **/
typedef struct xcb_xv_query_extension_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
} xcb_xv_query_extension_request_t;

/**
 * @brief xcb_xv_query_extension_reply_t
 **/
typedef struct xcb_xv_query_extension_reply_t {
    uint8_t  response_type;
    uint8_t  pad0;
    uint16_t sequence;
    uint32_t length;
    uint16_t major;
    uint16_t minor;
} xcb_xv_query_extension_reply_t;

/**
 * @brief xcb_xv_query_adaptors_cookie_t
 **/
typedef struct xcb_xv_query_adaptors_cookie_t {
    unsigned int sequence;
} xcb_xv_query_adaptors_cookie_t;

/** Opcode for xcb_xv_query_adaptors. */
#define XCB_XV_QUERY_ADAPTORS 1

/**
 * @brief xcb_xv_query_adaptors_request_t
 **/
typedef struct xcb_xv_query_adaptors_request_t {
    uint8_t      major_opcode;
    uint8_t      minor_opcode;
    uint16_t     length;
    xcb_window_t window;
} xcb_xv_query_adaptors_request_t;

/**
 * @brief xcb_xv_query_adaptors_reply_t
 **/
typedef struct xcb_xv_query_adaptors_reply_t {
    uint8_t  response_type;
    uint8_t  pad0;
    uint16_t sequence;
    uint32_t length;
    uint16_t num_adaptors;
    uint8_t  pad1[22];
} xcb_xv_query_adaptors_reply_t;

/**
 * @brief xcb_xv_query_encodings_cookie_t
 **/
typedef struct xcb_xv_query_encodings_cookie_t {
    unsigned int sequence;
} xcb_xv_query_encodings_cookie_t;

/** Opcode for xcb_xv_query_encodings. */
#define XCB_XV_QUERY_ENCODINGS 2

/**
 * @brief xcb_xv_query_encodings_request_t
 **/
typedef struct xcb_xv_query_encodings_request_t {
    uint8_t       major_opcode;
    uint8_t       minor_opcode;
    uint16_t      length;
    xcb_xv_port_t port;
} xcb_xv_query_encodings_request_t;

/**
 * @brief xcb_xv_query_encodings_reply_t
 **/
typedef struct xcb_xv_query_encodings_reply_t {
    uint8_t  response_type;
    uint8_t  pad0;
    uint16_t sequence;
    uint32_t length;
    uint16_t num_encodings;
    uint8_t  pad1[22];
} xcb_xv_query_encodings_reply_t;

/**
 * @brief xcb_xv_grab_port_cookie_t
 **/
typedef struct xcb_xv_grab_port_cookie_t {
    unsigned int sequence;
} xcb_xv_grab_port_cookie_t;

/** Opcode for xcb_xv_grab_port. */
#define XCB_XV_GRAB_PORT 3

/**
 * @brief xcb_xv_grab_port_request_t
 **/
typedef struct xcb_xv_grab_port_request_t {
    uint8_t         major_opcode;
    uint8_t         minor_opcode;
    uint16_t        length;
    xcb_xv_port_t   port;
    xcb_timestamp_t time;
} xcb_xv_grab_port_request_t;

/**
 * @brief xcb_xv_grab_port_reply_t
 **/
typedef struct xcb_xv_grab_port_reply_t {
    uint8_t  response_type;
    uint8_t  result;
    uint16_t sequence;
    uint32_t length;
} xcb_xv_grab_port_reply_t;

/** Opcode for xcb_xv_ungrab_port. */
#define XCB_XV_UNGRAB_PORT 4

/**
 * @brief xcb_xv_ungrab_port_request_t
 **/
typedef struct xcb_xv_ungrab_port_request_t {
    uint8_t         major_opcode;
    uint8_t         minor_opcode;
    uint16_t        length;
    xcb_xv_port_t   port;
    xcb_timestamp_t time;
} xcb_xv_ungrab_port_request_t;

/** Opcode for xcb_xv_put_video. */
#define XCB_XV_PUT_VIDEO 5

/**
 * @brief xcb_xv_put_video_request_t
 **/
typedef struct xcb_xv_put_video_request_t {
    uint8_t        major_opcode;
    uint8_t        minor_opcode;
    uint16_t       length;
    xcb_xv_port_t  port;
    xcb_drawable_t drawable;
    xcb_gcontext_t gc;
    int16_t        vid_x;
    int16_t        vid_y;
    uint16_t       vid_w;
    uint16_t       vid_h;
    int16_t        drw_x;
    int16_t        drw_y;
    uint16_t       drw_w;
    uint16_t       drw_h;
} xcb_xv_put_video_request_t;

/** Opcode for xcb_xv_put_still. */
#define XCB_XV_PUT_STILL 6

/**
 * @brief xcb_xv_put_still_request_t
 **/
typedef struct xcb_xv_put_still_request_t {
    uint8_t        major_opcode;
    uint8_t        minor_opcode;
    uint16_t       length;
    xcb_xv_port_t  port;
    xcb_drawable_t drawable;
    xcb_gcontext_t gc;
    int16_t        vid_x;
    int16_t        vid_y;
    uint16_t       vid_w;
    uint16_t       vid_h;
    int16_t        drw_x;
    int16_t        drw_y;
    uint16_t       drw_w;
    uint16_t       drw_h;
} xcb_xv_put_still_request_t;

/** Opcode for xcb_xv_get_video. */
#define XCB_XV_GET_VIDEO 7

/**
 * @brief xcb_xv_get_video_request_t
 **/
typedef struct xcb_xv_get_video_request_t {
    uint8_t        major_opcode;
    uint8_t        minor_opcode;
    uint16_t       length;
    xcb_xv_port_t  port;
    xcb_drawable_t drawable;
    xcb_gcontext_t gc;
    int16_t        vid_x;
    int16_t        vid_y;
    uint16_t       vid_w;
    uint16_t       vid_h;
    int16_t        drw_x;
    int16_t        drw_y;
    uint16_t       drw_w;
    uint16_t       drw_h;
} xcb_xv_get_video_request_t;

/** Opcode for xcb_xv_get_still. */
#define XCB_XV_GET_STILL 8

/**
 * @brief xcb_xv_get_still_request_t
 **/
typedef struct xcb_xv_get_still_request_t {
    uint8_t        major_opcode;
    uint8_t        minor_opcode;
    uint16_t       length;
    xcb_xv_port_t  port;
    xcb_drawable_t drawable;
    xcb_gcontext_t gc;
    int16_t        vid_x;
    int16_t        vid_y;
    uint16_t       vid_w;
    uint16_t       vid_h;
    int16_t        drw_x;
    int16_t        drw_y;
    uint16_t       drw_w;
    uint16_t       drw_h;
} xcb_xv_get_still_request_t;

/** Opcode for xcb_xv_stop_video. */
#define XCB_XV_STOP_VIDEO 9

/**
 * @brief xcb_xv_stop_video_request_t
 **/
typedef struct xcb_xv_stop_video_request_t {
    uint8_t        major_opcode;
    uint8_t        minor_opcode;
    uint16_t       length;
    xcb_xv_port_t  port;
    xcb_drawable_t drawable;
} xcb_xv_stop_video_request_t;

/** Opcode for xcb_xv_select_video_notify. */
#define XCB_XV_SELECT_VIDEO_NOTIFY 10

/**
 * @brief xcb_xv_select_video_notify_request_t
 **/
typedef struct xcb_xv_select_video_notify_request_t {
    uint8_t        major_opcode;
    uint8_t        minor_opcode;
    uint16_t       length;
    xcb_drawable_t drawable;
    uint8_t        onoff;
    uint8_t        pad0[3];
} xcb_xv_select_video_notify_request_t;

/** Opcode for xcb_xv_select_port_notify. */
#define XCB_XV_SELECT_PORT_NOTIFY 11

/**
 * @brief xcb_xv_select_port_notify_request_t
 **/
typedef struct xcb_xv_select_port_notify_request_t {
    uint8_t       major_opcode;
    uint8_t       minor_opcode;
    uint16_t      length;
    xcb_xv_port_t port;
    uint8_t       onoff;
    uint8_t       pad0[3];
} xcb_xv_select_port_notify_request_t;

/**
 * @brief xcb_xv_query_best_size_cookie_t
 **/
typedef struct xcb_xv_query_best_size_cookie_t {
    unsigned int sequence;
} xcb_xv_query_best_size_cookie_t;

/** Opcode for xcb_xv_query_best_size. */
#define XCB_XV_QUERY_BEST_SIZE 12

/**
 * @brief xcb_xv_query_best_size_request_t
 **/
typedef struct xcb_xv_query_best_size_request_t {
    uint8_t       major_opcode;
    uint8_t       minor_opcode;
    uint16_t      length;
    xcb_xv_port_t port;
    uint16_t      vid_w;
    uint16_t      vid_h;
    uint16_t      drw_w;
    uint16_t      drw_h;
    uint8_t       motion;
    uint8_t       pad0[3];
} xcb_xv_query_best_size_request_t;

/**
 * @brief xcb_xv_query_best_size_reply_t
 **/
typedef struct xcb_xv_query_best_size_reply_t {
    uint8_t  response_type;
    uint8_t  pad0;
    uint16_t sequence;
    uint32_t length;
    uint16_t actual_width;
    uint16_t actual_height;
} xcb_xv_query_best_size_reply_t;

/** Opcode for xcb_xv_set_port_attribute. */
#define XCB_XV_SET_PORT_ATTRIBUTE 13

/**
 * @brief xcb_xv_set_port_attribute_request_t
 **/
typedef struct xcb_xv_set_port_attribute_request_t {
    uint8_t       major_opcode;
    uint8_t       minor_opcode;
    uint16_t      length;
    xcb_xv_port_t port;
    xcb_atom_t    attribute;
    int32_t       value;
} xcb_xv_set_port_attribute_request_t;

/**
 * @brief xcb_xv_get_port_attribute_cookie_t
 **/
typedef struct xcb_xv_get_port_attribute_cookie_t {
    unsigned int sequence;
} xcb_xv_get_port_attribute_cookie_t;

/** Opcode for xcb_xv_get_port_attribute. */
#define XCB_XV_GET_PORT_ATTRIBUTE 14

/**
 * @brief xcb_xv_get_port_attribute_request_t
 **/
typedef struct xcb_xv_get_port_attribute_request_t {
    uint8_t       major_opcode;
    uint8_t       minor_opcode;
    uint16_t      length;
    xcb_xv_port_t port;
    xcb_atom_t    attribute;
} xcb_xv_get_port_attribute_request_t;

/**
 * @brief xcb_xv_get_port_attribute_reply_t
 **/
typedef struct xcb_xv_get_port_attribute_reply_t {
    uint8_t  response_type;
    uint8_t  pad0;
    uint16_t sequence;
    uint32_t length;
    int32_t  value;
} xcb_xv_get_port_attribute_reply_t;

/**
 * @brief xcb_xv_query_port_attributes_cookie_t
 **/
typedef struct xcb_xv_query_port_attributes_cookie_t {
    unsigned int sequence;
} xcb_xv_query_port_attributes_cookie_t;

/** Opcode for xcb_xv_query_port_attributes. */
#define XCB_XV_QUERY_PORT_ATTRIBUTES 15

/**
 * @brief xcb_xv_query_port_attributes_request_t
 **/
typedef struct xcb_xv_query_port_attributes_request_t {
    uint8_t       major_opcode;
    uint8_t       minor_opcode;
    uint16_t      length;
    xcb_xv_port_t port;
} xcb_xv_query_port_attributes_request_t;

/**
 * @brief xcb_xv_query_port_attributes_reply_t
 **/
typedef struct xcb_xv_query_port_attributes_reply_t {
    uint8_t  response_type;
    uint8_t  pad0;
    uint16_t sequence;
    uint32_t length;
    uint32_t num_attributes;
    uint32_t text_size;
    uint8_t  pad1[16];
} xcb_xv_query_port_attributes_reply_t;

/**
 * @brief xcb_xv_list_image_formats_cookie_t
 **/
typedef struct xcb_xv_list_image_formats_cookie_t {
    unsigned int sequence;
} xcb_xv_list_image_formats_cookie_t;

/** Opcode for xcb_xv_list_image_formats. */
#define XCB_XV_LIST_IMAGE_FORMATS 16

/**
 * @brief xcb_xv_list_image_formats_request_t
 **/
typedef struct xcb_xv_list_image_formats_request_t {
    uint8_t       major_opcode;
    uint8_t       minor_opcode;
    uint16_t      length;
    xcb_xv_port_t port;
} xcb_xv_list_image_formats_request_t;

/**
 * @brief xcb_xv_list_image_formats_reply_t
 **/
typedef struct xcb_xv_list_image_formats_reply_t {
    uint8_t  response_type;
    uint8_t  pad0;
    uint16_t sequence;
    uint32_t length;
    uint32_t num_formats;
    uint8_t  pad1[20];
} xcb_xv_list_image_formats_reply_t;

/**
 * @brief xcb_xv_query_image_attributes_cookie_t
 **/
typedef struct xcb_xv_query_image_attributes_cookie_t {
    unsigned int sequence;
} xcb_xv_query_image_attributes_cookie_t;

/** Opcode for xcb_xv_query_image_attributes. */
#define XCB_XV_QUERY_IMAGE_ATTRIBUTES 17

/**
 * @brief xcb_xv_query_image_attributes_request_t
 **/
typedef struct xcb_xv_query_image_attributes_request_t {
    uint8_t       major_opcode;
    uint8_t       minor_opcode;
    uint16_t      length;
    xcb_xv_port_t port;
    uint32_t      id;
    uint16_t      width;
    uint16_t      height;
} xcb_xv_query_image_attributes_request_t;

/**
 * @brief xcb_xv_query_image_attributes_reply_t
 **/
typedef struct xcb_xv_query_image_attributes_reply_t {
    uint8_t  response_type;
    uint8_t  pad0;
    uint16_t sequence;
    uint32_t length;
    uint32_t num_planes;
    uint32_t data_size;
    uint16_t width;
    uint16_t height;
    uint8_t  pad1[12];
} xcb_xv_query_image_attributes_reply_t;

/** Opcode for xcb_xv_put_image. */
#define XCB_XV_PUT_IMAGE 18

/**
 * @brief xcb_xv_put_image_request_t
 **/
typedef struct xcb_xv_put_image_request_t {
    uint8_t        major_opcode;
    uint8_t        minor_opcode;
    uint16_t       length;
    xcb_xv_port_t  port;
    xcb_drawable_t drawable;
    xcb_gcontext_t gc;
    uint32_t       id;
    int16_t        src_x;
    int16_t        src_y;
    uint16_t       src_w;
    uint16_t       src_h;
    int16_t        drw_x;
    int16_t        drw_y;
    uint16_t       drw_w;
    uint16_t       drw_h;
    uint16_t       width;
    uint16_t       height;
} xcb_xv_put_image_request_t;

/** Opcode for xcb_xv_shm_put_image. */
#define XCB_XV_SHM_PUT_IMAGE 19

/**
 * @brief xcb_xv_shm_put_image_request_t
 **/
typedef struct xcb_xv_shm_put_image_request_t {
    uint8_t        major_opcode;
    uint8_t        minor_opcode;
    uint16_t       length;
    xcb_xv_port_t  port;
    xcb_drawable_t drawable;
    xcb_gcontext_t gc;
    xcb_shm_seg_t  shmseg;
    uint32_t       id;
    uint32_t       offset;
    int16_t        src_x;
    int16_t        src_y;
    uint16_t       src_w;
    uint16_t       src_h;
    int16_t        drw_x;
    int16_t        drw_y;
    uint16_t       drw_w;
    uint16_t       drw_h;
    uint16_t       width;
    uint16_t       height;
    uint8_t        send_event;
    uint8_t        pad0[3];
} xcb_xv_shm_put_image_request_t;

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xv_port_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xv_port_t)
 */
void
xcb_xv_port_next (xcb_xv_port_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xv_port_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xv_port_end (xcb_xv_port_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xv_encoding_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xv_encoding_t)
 */
void
xcb_xv_encoding_next (xcb_xv_encoding_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xv_encoding_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xv_encoding_end (xcb_xv_encoding_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xv_rational_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xv_rational_t)
 */
void
xcb_xv_rational_next (xcb_xv_rational_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xv_rational_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xv_rational_end (xcb_xv_rational_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xv_format_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xv_format_t)
 */
void
xcb_xv_format_next (xcb_xv_format_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xv_format_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xv_format_end (xcb_xv_format_iterator_t i);

int
xcb_xv_adaptor_info_sizeof (const void  *_buffer);

char *
xcb_xv_adaptor_info_name (const xcb_xv_adaptor_info_t *R);

int
xcb_xv_adaptor_info_name_length (const xcb_xv_adaptor_info_t *R);

xcb_generic_iterator_t
xcb_xv_adaptor_info_name_end (const xcb_xv_adaptor_info_t *R);

xcb_xv_format_t *
xcb_xv_adaptor_info_formats (const xcb_xv_adaptor_info_t *R);

int
xcb_xv_adaptor_info_formats_length (const xcb_xv_adaptor_info_t *R);

xcb_xv_format_iterator_t
xcb_xv_adaptor_info_formats_iterator (const xcb_xv_adaptor_info_t *R);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xv_adaptor_info_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xv_adaptor_info_t)
 */
void
xcb_xv_adaptor_info_next (xcb_xv_adaptor_info_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xv_adaptor_info_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xv_adaptor_info_end (xcb_xv_adaptor_info_iterator_t i);

int
xcb_xv_encoding_info_sizeof (const void  *_buffer);

char *
xcb_xv_encoding_info_name (const xcb_xv_encoding_info_t *R);

int
xcb_xv_encoding_info_name_length (const xcb_xv_encoding_info_t *R);

xcb_generic_iterator_t
xcb_xv_encoding_info_name_end (const xcb_xv_encoding_info_t *R);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xv_encoding_info_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xv_encoding_info_t)
 */
void
xcb_xv_encoding_info_next (xcb_xv_encoding_info_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xv_encoding_info_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xv_encoding_info_end (xcb_xv_encoding_info_iterator_t i);

int
xcb_xv_image_sizeof (const void  *_buffer);

uint32_t *
xcb_xv_image_pitches (const xcb_xv_image_t *R);

int
xcb_xv_image_pitches_length (const xcb_xv_image_t *R);

xcb_generic_iterator_t
xcb_xv_image_pitches_end (const xcb_xv_image_t *R);

uint32_t *
xcb_xv_image_offsets (const xcb_xv_image_t *R);

int
xcb_xv_image_offsets_length (const xcb_xv_image_t *R);

xcb_generic_iterator_t
xcb_xv_image_offsets_end (const xcb_xv_image_t *R);

uint8_t *
xcb_xv_image_data (const xcb_xv_image_t *R);

int
xcb_xv_image_data_length (const xcb_xv_image_t *R);

xcb_generic_iterator_t
xcb_xv_image_data_end (const xcb_xv_image_t *R);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xv_image_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xv_image_t)
 */
void
xcb_xv_image_next (xcb_xv_image_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xv_image_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xv_image_end (xcb_xv_image_iterator_t i);

int
xcb_xv_attribute_info_sizeof (const void  *_buffer);

char *
xcb_xv_attribute_info_name (const xcb_xv_attribute_info_t *R);

int
xcb_xv_attribute_info_name_length (const xcb_xv_attribute_info_t *R);

xcb_generic_iterator_t
xcb_xv_attribute_info_name_end (const xcb_xv_attribute_info_t *R);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xv_attribute_info_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xv_attribute_info_t)
 */
void
xcb_xv_attribute_info_next (xcb_xv_attribute_info_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xv_attribute_info_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xv_attribute_info_end (xcb_xv_attribute_info_iterator_t i);

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xv_image_format_info_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xv_image_format_info_t)
 */
void
xcb_xv_image_format_info_next (xcb_xv_image_format_info_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xv_image_format_info_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xv_image_format_info_end (xcb_xv_image_format_info_iterator_t i);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_xv_query_extension_cookie_t
xcb_xv_query_extension (xcb_connection_t *c);

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
xcb_xv_query_extension_cookie_t
xcb_xv_query_extension_unchecked (xcb_connection_t *c);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_xv_query_extension_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_xv_query_extension_reply_t *
xcb_xv_query_extension_reply (xcb_connection_t                 *c,
                              xcb_xv_query_extension_cookie_t   cookie  /**< */,
                              xcb_generic_error_t             **e);

int
xcb_xv_query_adaptors_sizeof (const void  *_buffer);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_xv_query_adaptors_cookie_t
xcb_xv_query_adaptors (xcb_connection_t *c,
                       xcb_window_t      window);

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
xcb_xv_query_adaptors_cookie_t
xcb_xv_query_adaptors_unchecked (xcb_connection_t *c,
                                 xcb_window_t      window);

int
xcb_xv_query_adaptors_info_length (const xcb_xv_query_adaptors_reply_t *R);

xcb_xv_adaptor_info_iterator_t
xcb_xv_query_adaptors_info_iterator (const xcb_xv_query_adaptors_reply_t *R);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_xv_query_adaptors_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_xv_query_adaptors_reply_t *
xcb_xv_query_adaptors_reply (xcb_connection_t                *c,
                             xcb_xv_query_adaptors_cookie_t   cookie  /**< */,
                             xcb_generic_error_t            **e);

int
xcb_xv_query_encodings_sizeof (const void  *_buffer);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_xv_query_encodings_cookie_t
xcb_xv_query_encodings (xcb_connection_t *c,
                        xcb_xv_port_t     port);

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
xcb_xv_query_encodings_cookie_t
xcb_xv_query_encodings_unchecked (xcb_connection_t *c,
                                  xcb_xv_port_t     port);

int
xcb_xv_query_encodings_info_length (const xcb_xv_query_encodings_reply_t *R);

xcb_xv_encoding_info_iterator_t
xcb_xv_query_encodings_info_iterator (const xcb_xv_query_encodings_reply_t *R);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_xv_query_encodings_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_xv_query_encodings_reply_t *
xcb_xv_query_encodings_reply (xcb_connection_t                 *c,
                              xcb_xv_query_encodings_cookie_t   cookie  /**< */,
                              xcb_generic_error_t             **e);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_xv_grab_port_cookie_t
xcb_xv_grab_port (xcb_connection_t *c,
                  xcb_xv_port_t     port,
                  xcb_timestamp_t   time);

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
xcb_xv_grab_port_cookie_t
xcb_xv_grab_port_unchecked (xcb_connection_t *c,
                            xcb_xv_port_t     port,
                            xcb_timestamp_t   time);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_xv_grab_port_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_xv_grab_port_reply_t *
xcb_xv_grab_port_reply (xcb_connection_t           *c,
                        xcb_xv_grab_port_cookie_t   cookie  /**< */,
                        xcb_generic_error_t       **e);

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
xcb_xv_ungrab_port_checked (xcb_connection_t *c,
                            xcb_xv_port_t     port,
                            xcb_timestamp_t   time);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_void_cookie_t
xcb_xv_ungrab_port (xcb_connection_t *c,
                    xcb_xv_port_t     port,
                    xcb_timestamp_t   time);

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
xcb_xv_put_video_checked (xcb_connection_t *c,
                          xcb_xv_port_t     port,
                          xcb_drawable_t    drawable,
                          xcb_gcontext_t    gc,
                          int16_t           vid_x,
                          int16_t           vid_y,
                          uint16_t          vid_w,
                          uint16_t          vid_h,
                          int16_t           drw_x,
                          int16_t           drw_y,
                          uint16_t          drw_w,
                          uint16_t          drw_h);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_void_cookie_t
xcb_xv_put_video (xcb_connection_t *c,
                  xcb_xv_port_t     port,
                  xcb_drawable_t    drawable,
                  xcb_gcontext_t    gc,
                  int16_t           vid_x,
                  int16_t           vid_y,
                  uint16_t          vid_w,
                  uint16_t          vid_h,
                  int16_t           drw_x,
                  int16_t           drw_y,
                  uint16_t          drw_w,
                  uint16_t          drw_h);

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
xcb_xv_put_still_checked (xcb_connection_t *c,
                          xcb_xv_port_t     port,
                          xcb_drawable_t    drawable,
                          xcb_gcontext_t    gc,
                          int16_t           vid_x,
                          int16_t           vid_y,
                          uint16_t          vid_w,
                          uint16_t          vid_h,
                          int16_t           drw_x,
                          int16_t           drw_y,
                          uint16_t          drw_w,
                          uint16_t          drw_h);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_void_cookie_t
xcb_xv_put_still (xcb_connection_t *c,
                  xcb_xv_port_t     port,
                  xcb_drawable_t    drawable,
                  xcb_gcontext_t    gc,
                  int16_t           vid_x,
                  int16_t           vid_y,
                  uint16_t          vid_w,
                  uint16_t          vid_h,
                  int16_t           drw_x,
                  int16_t           drw_y,
                  uint16_t          drw_w,
                  uint16_t          drw_h);

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
xcb_xv_get_video_checked (xcb_connection_t *c,
                          xcb_xv_port_t     port,
                          xcb_drawable_t    drawable,
                          xcb_gcontext_t    gc,
                          int16_t           vid_x,
                          int16_t           vid_y,
                          uint16_t          vid_w,
                          uint16_t          vid_h,
                          int16_t           drw_x,
                          int16_t           drw_y,
                          uint16_t          drw_w,
                          uint16_t          drw_h);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_void_cookie_t
xcb_xv_get_video (xcb_connection_t *c,
                  xcb_xv_port_t     port,
                  xcb_drawable_t    drawable,
                  xcb_gcontext_t    gc,
                  int16_t           vid_x,
                  int16_t           vid_y,
                  uint16_t          vid_w,
                  uint16_t          vid_h,
                  int16_t           drw_x,
                  int16_t           drw_y,
                  uint16_t          drw_w,
                  uint16_t          drw_h);

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
xcb_xv_get_still_checked (xcb_connection_t *c,
                          xcb_xv_port_t     port,
                          xcb_drawable_t    drawable,
                          xcb_gcontext_t    gc,
                          int16_t           vid_x,
                          int16_t           vid_y,
                          uint16_t          vid_w,
                          uint16_t          vid_h,
                          int16_t           drw_x,
                          int16_t           drw_y,
                          uint16_t          drw_w,
                          uint16_t          drw_h);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_void_cookie_t
xcb_xv_get_still (xcb_connection_t *c,
                  xcb_xv_port_t     port,
                  xcb_drawable_t    drawable,
                  xcb_gcontext_t    gc,
                  int16_t           vid_x,
                  int16_t           vid_y,
                  uint16_t          vid_w,
                  uint16_t          vid_h,
                  int16_t           drw_x,
                  int16_t           drw_y,
                  uint16_t          drw_w,
                  uint16_t          drw_h);

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
xcb_xv_stop_video_checked (xcb_connection_t *c,
                           xcb_xv_port_t     port,
                           xcb_drawable_t    drawable);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_void_cookie_t
xcb_xv_stop_video (xcb_connection_t *c,
                   xcb_xv_port_t     port,
                   xcb_drawable_t    drawable);

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
xcb_xv_select_video_notify_checked (xcb_connection_t *c,
                                    xcb_drawable_t    drawable,
                                    uint8_t           onoff);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_void_cookie_t
xcb_xv_select_video_notify (xcb_connection_t *c,
                            xcb_drawable_t    drawable,
                            uint8_t           onoff);

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
xcb_xv_select_port_notify_checked (xcb_connection_t *c,
                                   xcb_xv_port_t     port,
                                   uint8_t           onoff);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_void_cookie_t
xcb_xv_select_port_notify (xcb_connection_t *c,
                           xcb_xv_port_t     port,
                           uint8_t           onoff);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_xv_query_best_size_cookie_t
xcb_xv_query_best_size (xcb_connection_t *c,
                        xcb_xv_port_t     port,
                        uint16_t          vid_w,
                        uint16_t          vid_h,
                        uint16_t          drw_w,
                        uint16_t          drw_h,
                        uint8_t           motion);

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
xcb_xv_query_best_size_cookie_t
xcb_xv_query_best_size_unchecked (xcb_connection_t *c,
                                  xcb_xv_port_t     port,
                                  uint16_t          vid_w,
                                  uint16_t          vid_h,
                                  uint16_t          drw_w,
                                  uint16_t          drw_h,
                                  uint8_t           motion);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_xv_query_best_size_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_xv_query_best_size_reply_t *
xcb_xv_query_best_size_reply (xcb_connection_t                 *c,
                              xcb_xv_query_best_size_cookie_t   cookie  /**< */,
                              xcb_generic_error_t             **e);

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
xcb_xv_set_port_attribute_checked (xcb_connection_t *c,
                                   xcb_xv_port_t     port,
                                   xcb_atom_t        attribute,
                                   int32_t           value);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_void_cookie_t
xcb_xv_set_port_attribute (xcb_connection_t *c,
                           xcb_xv_port_t     port,
                           xcb_atom_t        attribute,
                           int32_t           value);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_xv_get_port_attribute_cookie_t
xcb_xv_get_port_attribute (xcb_connection_t *c,
                           xcb_xv_port_t     port,
                           xcb_atom_t        attribute);

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
xcb_xv_get_port_attribute_cookie_t
xcb_xv_get_port_attribute_unchecked (xcb_connection_t *c,
                                     xcb_xv_port_t     port,
                                     xcb_atom_t        attribute);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_xv_get_port_attribute_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_xv_get_port_attribute_reply_t *
xcb_xv_get_port_attribute_reply (xcb_connection_t                    *c,
                                 xcb_xv_get_port_attribute_cookie_t   cookie  /**< */,
                                 xcb_generic_error_t                **e);

int
xcb_xv_query_port_attributes_sizeof (const void  *_buffer);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_xv_query_port_attributes_cookie_t
xcb_xv_query_port_attributes (xcb_connection_t *c,
                              xcb_xv_port_t     port);

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
xcb_xv_query_port_attributes_cookie_t
xcb_xv_query_port_attributes_unchecked (xcb_connection_t *c,
                                        xcb_xv_port_t     port);

int
xcb_xv_query_port_attributes_attributes_length (const xcb_xv_query_port_attributes_reply_t *R);

xcb_xv_attribute_info_iterator_t
xcb_xv_query_port_attributes_attributes_iterator (const xcb_xv_query_port_attributes_reply_t *R);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_xv_query_port_attributes_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_xv_query_port_attributes_reply_t *
xcb_xv_query_port_attributes_reply (xcb_connection_t                       *c,
                                    xcb_xv_query_port_attributes_cookie_t   cookie  /**< */,
                                    xcb_generic_error_t                   **e);

int
xcb_xv_list_image_formats_sizeof (const void  *_buffer);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_xv_list_image_formats_cookie_t
xcb_xv_list_image_formats (xcb_connection_t *c,
                           xcb_xv_port_t     port);

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
xcb_xv_list_image_formats_cookie_t
xcb_xv_list_image_formats_unchecked (xcb_connection_t *c,
                                     xcb_xv_port_t     port);

xcb_xv_image_format_info_t *
xcb_xv_list_image_formats_format (const xcb_xv_list_image_formats_reply_t *R);

int
xcb_xv_list_image_formats_format_length (const xcb_xv_list_image_formats_reply_t *R);

xcb_xv_image_format_info_iterator_t
xcb_xv_list_image_formats_format_iterator (const xcb_xv_list_image_formats_reply_t *R);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_xv_list_image_formats_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_xv_list_image_formats_reply_t *
xcb_xv_list_image_formats_reply (xcb_connection_t                    *c,
                                 xcb_xv_list_image_formats_cookie_t   cookie  /**< */,
                                 xcb_generic_error_t                **e);

int
xcb_xv_query_image_attributes_sizeof (const void  *_buffer);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_xv_query_image_attributes_cookie_t
xcb_xv_query_image_attributes (xcb_connection_t *c,
                               xcb_xv_port_t     port,
                               uint32_t          id,
                               uint16_t          width,
                               uint16_t          height);

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
xcb_xv_query_image_attributes_cookie_t
xcb_xv_query_image_attributes_unchecked (xcb_connection_t *c,
                                         xcb_xv_port_t     port,
                                         uint32_t          id,
                                         uint16_t          width,
                                         uint16_t          height);

uint32_t *
xcb_xv_query_image_attributes_pitches (const xcb_xv_query_image_attributes_reply_t *R);

int
xcb_xv_query_image_attributes_pitches_length (const xcb_xv_query_image_attributes_reply_t *R);

xcb_generic_iterator_t
xcb_xv_query_image_attributes_pitches_end (const xcb_xv_query_image_attributes_reply_t *R);

uint32_t *
xcb_xv_query_image_attributes_offsets (const xcb_xv_query_image_attributes_reply_t *R);

int
xcb_xv_query_image_attributes_offsets_length (const xcb_xv_query_image_attributes_reply_t *R);

xcb_generic_iterator_t
xcb_xv_query_image_attributes_offsets_end (const xcb_xv_query_image_attributes_reply_t *R);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_xv_query_image_attributes_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_xv_query_image_attributes_reply_t *
xcb_xv_query_image_attributes_reply (xcb_connection_t                        *c,
                                     xcb_xv_query_image_attributes_cookie_t   cookie  /**< */,
                                     xcb_generic_error_t                    **e);

int
xcb_xv_put_image_sizeof (const void  *_buffer,
                         uint32_t     data_len);

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
xcb_xv_put_image_checked (xcb_connection_t *c,
                          xcb_xv_port_t     port,
                          xcb_drawable_t    drawable,
                          xcb_gcontext_t    gc,
                          uint32_t          id,
                          int16_t           src_x,
                          int16_t           src_y,
                          uint16_t          src_w,
                          uint16_t          src_h,
                          int16_t           drw_x,
                          int16_t           drw_y,
                          uint16_t          drw_w,
                          uint16_t          drw_h,
                          uint16_t          width,
                          uint16_t          height,
                          uint32_t          data_len,
                          const uint8_t    *data);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_void_cookie_t
xcb_xv_put_image (xcb_connection_t *c,
                  xcb_xv_port_t     port,
                  xcb_drawable_t    drawable,
                  xcb_gcontext_t    gc,
                  uint32_t          id,
                  int16_t           src_x,
                  int16_t           src_y,
                  uint16_t          src_w,
                  uint16_t          src_h,
                  int16_t           drw_x,
                  int16_t           drw_y,
                  uint16_t          drw_w,
                  uint16_t          drw_h,
                  uint16_t          width,
                  uint16_t          height,
                  uint32_t          data_len,
                  const uint8_t    *data);

uint8_t *
xcb_xv_put_image_data (const xcb_xv_put_image_request_t *R);

int
xcb_xv_put_image_data_length (const xcb_xv_put_image_request_t *R);

xcb_generic_iterator_t
xcb_xv_put_image_data_end (const xcb_xv_put_image_request_t *R);

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
xcb_xv_shm_put_image_checked (xcb_connection_t *c,
                              xcb_xv_port_t     port,
                              xcb_drawable_t    drawable,
                              xcb_gcontext_t    gc,
                              xcb_shm_seg_t     shmseg,
                              uint32_t          id,
                              uint32_t          offset,
                              int16_t           src_x,
                              int16_t           src_y,
                              uint16_t          src_w,
                              uint16_t          src_h,
                              int16_t           drw_x,
                              int16_t           drw_y,
                              uint16_t          drw_w,
                              uint16_t          drw_h,
                              uint16_t          width,
                              uint16_t          height,
                              uint8_t           send_event);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_void_cookie_t
xcb_xv_shm_put_image (xcb_connection_t *c,
                      xcb_xv_port_t     port,
                      xcb_drawable_t    drawable,
                      xcb_gcontext_t    gc,
                      xcb_shm_seg_t     shmseg,
                      uint32_t          id,
                      uint32_t          offset,
                      int16_t           src_x,
                      int16_t           src_y,
                      uint16_t          src_w,
                      uint16_t          src_h,
                      int16_t           drw_x,
                      int16_t           drw_y,
                      uint16_t          drw_w,
                      uint16_t          drw_h,
                      uint16_t          width,
                      uint16_t          height,
                      uint8_t           send_event);


#ifdef __cplusplus
}
#endif

#endif

/**
 * @}
 */
