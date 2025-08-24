/*
 * This file generated automatically from xf86dri.xml by c_client.py.
 * Edit at your peril.
 */

/**
 * @defgroup XCB_XF86Dri_API XCB XF86Dri API
 * @brief XF86Dri XCB Protocol Implementation.
 * @{
 **/

#ifndef __XF86DRI_H
#define __XF86DRI_H

#include "xcb.h"

#ifdef __cplusplus
extern "C" {
#endif

#define XCB_XF86DRI_MAJOR_VERSION 4
#define XCB_XF86DRI_MINOR_VERSION 1

extern xcb_extension_t xcb_xf86dri_id;

/**
 * @brief xcb_xf86dri_drm_clip_rect_t
 **/
typedef struct xcb_xf86dri_drm_clip_rect_t {
    int16_t x1;
    int16_t y1;
    int16_t x2;
    int16_t x3;
} xcb_xf86dri_drm_clip_rect_t;

/**
 * @brief xcb_xf86dri_drm_clip_rect_iterator_t
 **/
typedef struct xcb_xf86dri_drm_clip_rect_iterator_t {
    xcb_xf86dri_drm_clip_rect_t *data;
    int                          rem;
    int                          index;
} xcb_xf86dri_drm_clip_rect_iterator_t;

/**
 * @brief xcb_xf86dri_query_version_cookie_t
 **/
typedef struct xcb_xf86dri_query_version_cookie_t {
    unsigned int sequence;
} xcb_xf86dri_query_version_cookie_t;

/** Opcode for xcb_xf86dri_query_version. */
#define XCB_XF86DRI_QUERY_VERSION 0

/**
 * @brief xcb_xf86dri_query_version_request_t
 **/
typedef struct xcb_xf86dri_query_version_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
} xcb_xf86dri_query_version_request_t;

/**
 * @brief xcb_xf86dri_query_version_reply_t
 **/
typedef struct xcb_xf86dri_query_version_reply_t {
    uint8_t  response_type;
    uint8_t  pad0;
    uint16_t sequence;
    uint32_t length;
    uint16_t dri_major_version;
    uint16_t dri_minor_version;
    uint32_t dri_minor_patch;
} xcb_xf86dri_query_version_reply_t;

/**
 * @brief xcb_xf86dri_query_direct_rendering_capable_cookie_t
 **/
typedef struct xcb_xf86dri_query_direct_rendering_capable_cookie_t {
    unsigned int sequence;
} xcb_xf86dri_query_direct_rendering_capable_cookie_t;

/** Opcode for xcb_xf86dri_query_direct_rendering_capable. */
#define XCB_XF86DRI_QUERY_DIRECT_RENDERING_CAPABLE 1

/**
 * @brief xcb_xf86dri_query_direct_rendering_capable_request_t
 **/
typedef struct xcb_xf86dri_query_direct_rendering_capable_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
    uint32_t screen;
} xcb_xf86dri_query_direct_rendering_capable_request_t;

/**
 * @brief xcb_xf86dri_query_direct_rendering_capable_reply_t
 **/
typedef struct xcb_xf86dri_query_direct_rendering_capable_reply_t {
    uint8_t  response_type;
    uint8_t  pad0;
    uint16_t sequence;
    uint32_t length;
    uint8_t  is_capable;
} xcb_xf86dri_query_direct_rendering_capable_reply_t;

/**
 * @brief xcb_xf86dri_open_connection_cookie_t
 **/
typedef struct xcb_xf86dri_open_connection_cookie_t {
    unsigned int sequence;
} xcb_xf86dri_open_connection_cookie_t;

/** Opcode for xcb_xf86dri_open_connection. */
#define XCB_XF86DRI_OPEN_CONNECTION 2

/**
 * @brief xcb_xf86dri_open_connection_request_t
 **/
typedef struct xcb_xf86dri_open_connection_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
    uint32_t screen;
} xcb_xf86dri_open_connection_request_t;

/**
 * @brief xcb_xf86dri_open_connection_reply_t
 **/
typedef struct xcb_xf86dri_open_connection_reply_t {
    uint8_t  response_type;
    uint8_t  pad0;
    uint16_t sequence;
    uint32_t length;
    uint32_t sarea_handle_low;
    uint32_t sarea_handle_high;
    uint32_t bus_id_len;
    uint8_t  pad1[12];
} xcb_xf86dri_open_connection_reply_t;

/** Opcode for xcb_xf86dri_close_connection. */
#define XCB_XF86DRI_CLOSE_CONNECTION 3

/**
 * @brief xcb_xf86dri_close_connection_request_t
 **/
typedef struct xcb_xf86dri_close_connection_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
    uint32_t screen;
} xcb_xf86dri_close_connection_request_t;

/**
 * @brief xcb_xf86dri_get_client_driver_name_cookie_t
 **/
typedef struct xcb_xf86dri_get_client_driver_name_cookie_t {
    unsigned int sequence;
} xcb_xf86dri_get_client_driver_name_cookie_t;

/** Opcode for xcb_xf86dri_get_client_driver_name. */
#define XCB_XF86DRI_GET_CLIENT_DRIVER_NAME 4

/**
 * @brief xcb_xf86dri_get_client_driver_name_request_t
 **/
typedef struct xcb_xf86dri_get_client_driver_name_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
    uint32_t screen;
} xcb_xf86dri_get_client_driver_name_request_t;

/**
 * @brief xcb_xf86dri_get_client_driver_name_reply_t
 **/
typedef struct xcb_xf86dri_get_client_driver_name_reply_t {
    uint8_t  response_type;
    uint8_t  pad0;
    uint16_t sequence;
    uint32_t length;
    uint32_t client_driver_major_version;
    uint32_t client_driver_minor_version;
    uint32_t client_driver_patch_version;
    uint32_t client_driver_name_len;
    uint8_t  pad1[8];
} xcb_xf86dri_get_client_driver_name_reply_t;

/**
 * @brief xcb_xf86dri_create_context_cookie_t
 **/
typedef struct xcb_xf86dri_create_context_cookie_t {
    unsigned int sequence;
} xcb_xf86dri_create_context_cookie_t;

/** Opcode for xcb_xf86dri_create_context. */
#define XCB_XF86DRI_CREATE_CONTEXT 5

/**
 * @brief xcb_xf86dri_create_context_request_t
 **/
typedef struct xcb_xf86dri_create_context_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
    uint32_t screen;
    uint32_t visual;
    uint32_t context;
} xcb_xf86dri_create_context_request_t;

/**
 * @brief xcb_xf86dri_create_context_reply_t
 **/
typedef struct xcb_xf86dri_create_context_reply_t {
    uint8_t  response_type;
    uint8_t  pad0;
    uint16_t sequence;
    uint32_t length;
    uint32_t hw_context;
} xcb_xf86dri_create_context_reply_t;

/** Opcode for xcb_xf86dri_destroy_context. */
#define XCB_XF86DRI_DESTROY_CONTEXT 6

/**
 * @brief xcb_xf86dri_destroy_context_request_t
 **/
typedef struct xcb_xf86dri_destroy_context_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
    uint32_t screen;
    uint32_t context;
} xcb_xf86dri_destroy_context_request_t;

/**
 * @brief xcb_xf86dri_create_drawable_cookie_t
 **/
typedef struct xcb_xf86dri_create_drawable_cookie_t {
    unsigned int sequence;
} xcb_xf86dri_create_drawable_cookie_t;

/** Opcode for xcb_xf86dri_create_drawable. */
#define XCB_XF86DRI_CREATE_DRAWABLE 7

/**
 * @brief xcb_xf86dri_create_drawable_request_t
 **/
typedef struct xcb_xf86dri_create_drawable_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
    uint32_t screen;
    uint32_t drawable;
} xcb_xf86dri_create_drawable_request_t;

/**
 * @brief xcb_xf86dri_create_drawable_reply_t
 **/
typedef struct xcb_xf86dri_create_drawable_reply_t {
    uint8_t  response_type;
    uint8_t  pad0;
    uint16_t sequence;
    uint32_t length;
    uint32_t hw_drawable_handle;
} xcb_xf86dri_create_drawable_reply_t;

/** Opcode for xcb_xf86dri_destroy_drawable. */
#define XCB_XF86DRI_DESTROY_DRAWABLE 8

/**
 * @brief xcb_xf86dri_destroy_drawable_request_t
 **/
typedef struct xcb_xf86dri_destroy_drawable_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
    uint32_t screen;
    uint32_t drawable;
} xcb_xf86dri_destroy_drawable_request_t;

/**
 * @brief xcb_xf86dri_get_drawable_info_cookie_t
 **/
typedef struct xcb_xf86dri_get_drawable_info_cookie_t {
    unsigned int sequence;
} xcb_xf86dri_get_drawable_info_cookie_t;

/** Opcode for xcb_xf86dri_get_drawable_info. */
#define XCB_XF86DRI_GET_DRAWABLE_INFO 9

/**
 * @brief xcb_xf86dri_get_drawable_info_request_t
 **/
typedef struct xcb_xf86dri_get_drawable_info_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
    uint32_t screen;
    uint32_t drawable;
} xcb_xf86dri_get_drawable_info_request_t;

/**
 * @brief xcb_xf86dri_get_drawable_info_reply_t
 **/
typedef struct xcb_xf86dri_get_drawable_info_reply_t {
    uint8_t  response_type;
    uint8_t  pad0;
    uint16_t sequence;
    uint32_t length;
    uint32_t drawable_table_index;
    uint32_t drawable_table_stamp;
    int16_t  drawable_origin_X;
    int16_t  drawable_origin_Y;
    int16_t  drawable_size_W;
    int16_t  drawable_size_H;
    uint32_t num_clip_rects;
    int16_t  back_x;
    int16_t  back_y;
    uint32_t num_back_clip_rects;
} xcb_xf86dri_get_drawable_info_reply_t;

/**
 * @brief xcb_xf86dri_get_device_info_cookie_t
 **/
typedef struct xcb_xf86dri_get_device_info_cookie_t {
    unsigned int sequence;
} xcb_xf86dri_get_device_info_cookie_t;

/** Opcode for xcb_xf86dri_get_device_info. */
#define XCB_XF86DRI_GET_DEVICE_INFO 10

/**
 * @brief xcb_xf86dri_get_device_info_request_t
 **/
typedef struct xcb_xf86dri_get_device_info_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
    uint32_t screen;
} xcb_xf86dri_get_device_info_request_t;

/**
 * @brief xcb_xf86dri_get_device_info_reply_t
 **/
typedef struct xcb_xf86dri_get_device_info_reply_t {
    uint8_t  response_type;
    uint8_t  pad0;
    uint16_t sequence;
    uint32_t length;
    uint32_t framebuffer_handle_low;
    uint32_t framebuffer_handle_high;
    uint32_t framebuffer_origin_offset;
    uint32_t framebuffer_size;
    uint32_t framebuffer_stride;
    uint32_t device_private_size;
} xcb_xf86dri_get_device_info_reply_t;

/**
 * @brief xcb_xf86dri_auth_connection_cookie_t
 **/
typedef struct xcb_xf86dri_auth_connection_cookie_t {
    unsigned int sequence;
} xcb_xf86dri_auth_connection_cookie_t;

/** Opcode for xcb_xf86dri_auth_connection. */
#define XCB_XF86DRI_AUTH_CONNECTION 11

/**
 * @brief xcb_xf86dri_auth_connection_request_t
 **/
typedef struct xcb_xf86dri_auth_connection_request_t {
    uint8_t  major_opcode;
    uint8_t  minor_opcode;
    uint16_t length;
    uint32_t screen;
    uint32_t magic;
} xcb_xf86dri_auth_connection_request_t;

/**
 * @brief xcb_xf86dri_auth_connection_reply_t
 **/
typedef struct xcb_xf86dri_auth_connection_reply_t {
    uint8_t  response_type;
    uint8_t  pad0;
    uint16_t sequence;
    uint32_t length;
    uint32_t authenticated;
} xcb_xf86dri_auth_connection_reply_t;

/**
 * Get the next element of the iterator
 * @param i Pointer to a xcb_xf86dri_drm_clip_rect_iterator_t
 *
 * Get the next element in the iterator. The member rem is
 * decreased by one. The member data points to the next
 * element. The member index is increased by sizeof(xcb_xf86dri_drm_clip_rect_t)
 */
void
xcb_xf86dri_drm_clip_rect_next (xcb_xf86dri_drm_clip_rect_iterator_t *i);

/**
 * Return the iterator pointing to the last element
 * @param i An xcb_xf86dri_drm_clip_rect_iterator_t
 * @return  The iterator pointing to the last element
 *
 * Set the current element in the iterator to the last element.
 * The member rem is set to 0. The member data points to the
 * last element.
 */
xcb_generic_iterator_t
xcb_xf86dri_drm_clip_rect_end (xcb_xf86dri_drm_clip_rect_iterator_t i);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_xf86dri_query_version_cookie_t
xcb_xf86dri_query_version (xcb_connection_t *c);

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
xcb_xf86dri_query_version_cookie_t
xcb_xf86dri_query_version_unchecked (xcb_connection_t *c);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_xf86dri_query_version_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_xf86dri_query_version_reply_t *
xcb_xf86dri_query_version_reply (xcb_connection_t                    *c,
                                 xcb_xf86dri_query_version_cookie_t   cookie  /**< */,
                                 xcb_generic_error_t                **e);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_xf86dri_query_direct_rendering_capable_cookie_t
xcb_xf86dri_query_direct_rendering_capable (xcb_connection_t *c,
                                            uint32_t          screen);

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
xcb_xf86dri_query_direct_rendering_capable_cookie_t
xcb_xf86dri_query_direct_rendering_capable_unchecked (xcb_connection_t *c,
                                                      uint32_t          screen);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_xf86dri_query_direct_rendering_capable_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_xf86dri_query_direct_rendering_capable_reply_t *
xcb_xf86dri_query_direct_rendering_capable_reply (xcb_connection_t                                     *c,
                                                  xcb_xf86dri_query_direct_rendering_capable_cookie_t   cookie  /**< */,
                                                  xcb_generic_error_t                                 **e);

int
xcb_xf86dri_open_connection_sizeof (const void  *_buffer);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_xf86dri_open_connection_cookie_t
xcb_xf86dri_open_connection (xcb_connection_t *c,
                             uint32_t          screen);

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
xcb_xf86dri_open_connection_cookie_t
xcb_xf86dri_open_connection_unchecked (xcb_connection_t *c,
                                       uint32_t          screen);

char *
xcb_xf86dri_open_connection_bus_id (const xcb_xf86dri_open_connection_reply_t *R);

int
xcb_xf86dri_open_connection_bus_id_length (const xcb_xf86dri_open_connection_reply_t *R);

xcb_generic_iterator_t
xcb_xf86dri_open_connection_bus_id_end (const xcb_xf86dri_open_connection_reply_t *R);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_xf86dri_open_connection_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_xf86dri_open_connection_reply_t *
xcb_xf86dri_open_connection_reply (xcb_connection_t                      *c,
                                   xcb_xf86dri_open_connection_cookie_t   cookie  /**< */,
                                   xcb_generic_error_t                  **e);

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
xcb_xf86dri_close_connection_checked (xcb_connection_t *c,
                                      uint32_t          screen);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_void_cookie_t
xcb_xf86dri_close_connection (xcb_connection_t *c,
                              uint32_t          screen);

int
xcb_xf86dri_get_client_driver_name_sizeof (const void  *_buffer);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_xf86dri_get_client_driver_name_cookie_t
xcb_xf86dri_get_client_driver_name (xcb_connection_t *c,
                                    uint32_t          screen);

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
xcb_xf86dri_get_client_driver_name_cookie_t
xcb_xf86dri_get_client_driver_name_unchecked (xcb_connection_t *c,
                                              uint32_t          screen);

char *
xcb_xf86dri_get_client_driver_name_client_driver_name (const xcb_xf86dri_get_client_driver_name_reply_t *R);

int
xcb_xf86dri_get_client_driver_name_client_driver_name_length (const xcb_xf86dri_get_client_driver_name_reply_t *R);

xcb_generic_iterator_t
xcb_xf86dri_get_client_driver_name_client_driver_name_end (const xcb_xf86dri_get_client_driver_name_reply_t *R);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_xf86dri_get_client_driver_name_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_xf86dri_get_client_driver_name_reply_t *
xcb_xf86dri_get_client_driver_name_reply (xcb_connection_t                             *c,
                                          xcb_xf86dri_get_client_driver_name_cookie_t   cookie  /**< */,
                                          xcb_generic_error_t                         **e);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_xf86dri_create_context_cookie_t
xcb_xf86dri_create_context (xcb_connection_t *c,
                            uint32_t          screen,
                            uint32_t          visual,
                            uint32_t          context);

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
xcb_xf86dri_create_context_cookie_t
xcb_xf86dri_create_context_unchecked (xcb_connection_t *c,
                                      uint32_t          screen,
                                      uint32_t          visual,
                                      uint32_t          context);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_xf86dri_create_context_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_xf86dri_create_context_reply_t *
xcb_xf86dri_create_context_reply (xcb_connection_t                     *c,
                                  xcb_xf86dri_create_context_cookie_t   cookie  /**< */,
                                  xcb_generic_error_t                 **e);

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
xcb_xf86dri_destroy_context_checked (xcb_connection_t *c,
                                     uint32_t          screen,
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
xcb_xf86dri_destroy_context (xcb_connection_t *c,
                             uint32_t          screen,
                             uint32_t          context);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_xf86dri_create_drawable_cookie_t
xcb_xf86dri_create_drawable (xcb_connection_t *c,
                             uint32_t          screen,
                             uint32_t          drawable);

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
xcb_xf86dri_create_drawable_cookie_t
xcb_xf86dri_create_drawable_unchecked (xcb_connection_t *c,
                                       uint32_t          screen,
                                       uint32_t          drawable);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_xf86dri_create_drawable_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_xf86dri_create_drawable_reply_t *
xcb_xf86dri_create_drawable_reply (xcb_connection_t                      *c,
                                   xcb_xf86dri_create_drawable_cookie_t   cookie  /**< */,
                                   xcb_generic_error_t                  **e);

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
xcb_xf86dri_destroy_drawable_checked (xcb_connection_t *c,
                                      uint32_t          screen,
                                      uint32_t          drawable);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_void_cookie_t
xcb_xf86dri_destroy_drawable (xcb_connection_t *c,
                              uint32_t          screen,
                              uint32_t          drawable);

int
xcb_xf86dri_get_drawable_info_sizeof (const void  *_buffer);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_xf86dri_get_drawable_info_cookie_t
xcb_xf86dri_get_drawable_info (xcb_connection_t *c,
                               uint32_t          screen,
                               uint32_t          drawable);

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
xcb_xf86dri_get_drawable_info_cookie_t
xcb_xf86dri_get_drawable_info_unchecked (xcb_connection_t *c,
                                         uint32_t          screen,
                                         uint32_t          drawable);

xcb_xf86dri_drm_clip_rect_t *
xcb_xf86dri_get_drawable_info_clip_rects (const xcb_xf86dri_get_drawable_info_reply_t *R);

int
xcb_xf86dri_get_drawable_info_clip_rects_length (const xcb_xf86dri_get_drawable_info_reply_t *R);

xcb_xf86dri_drm_clip_rect_iterator_t
xcb_xf86dri_get_drawable_info_clip_rects_iterator (const xcb_xf86dri_get_drawable_info_reply_t *R);

xcb_xf86dri_drm_clip_rect_t *
xcb_xf86dri_get_drawable_info_back_clip_rects (const xcb_xf86dri_get_drawable_info_reply_t *R);

int
xcb_xf86dri_get_drawable_info_back_clip_rects_length (const xcb_xf86dri_get_drawable_info_reply_t *R);

xcb_xf86dri_drm_clip_rect_iterator_t
xcb_xf86dri_get_drawable_info_back_clip_rects_iterator (const xcb_xf86dri_get_drawable_info_reply_t *R);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_xf86dri_get_drawable_info_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_xf86dri_get_drawable_info_reply_t *
xcb_xf86dri_get_drawable_info_reply (xcb_connection_t                        *c,
                                     xcb_xf86dri_get_drawable_info_cookie_t   cookie  /**< */,
                                     xcb_generic_error_t                    **e);

int
xcb_xf86dri_get_device_info_sizeof (const void  *_buffer);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_xf86dri_get_device_info_cookie_t
xcb_xf86dri_get_device_info (xcb_connection_t *c,
                             uint32_t          screen);

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
xcb_xf86dri_get_device_info_cookie_t
xcb_xf86dri_get_device_info_unchecked (xcb_connection_t *c,
                                       uint32_t          screen);

uint32_t *
xcb_xf86dri_get_device_info_device_private (const xcb_xf86dri_get_device_info_reply_t *R);

int
xcb_xf86dri_get_device_info_device_private_length (const xcb_xf86dri_get_device_info_reply_t *R);

xcb_generic_iterator_t
xcb_xf86dri_get_device_info_device_private_end (const xcb_xf86dri_get_device_info_reply_t *R);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_xf86dri_get_device_info_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_xf86dri_get_device_info_reply_t *
xcb_xf86dri_get_device_info_reply (xcb_connection_t                      *c,
                                   xcb_xf86dri_get_device_info_cookie_t   cookie  /**< */,
                                   xcb_generic_error_t                  **e);

/**
 *
 * @param c The connection
 * @return A cookie
 *
 * Delivers a request to the X server.
 *
 */
xcb_xf86dri_auth_connection_cookie_t
xcb_xf86dri_auth_connection (xcb_connection_t *c,
                             uint32_t          screen,
                             uint32_t          magic);

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
xcb_xf86dri_auth_connection_cookie_t
xcb_xf86dri_auth_connection_unchecked (xcb_connection_t *c,
                                       uint32_t          screen,
                                       uint32_t          magic);

/**
 * Return the reply
 * @param c      The connection
 * @param cookie The cookie
 * @param e      The xcb_generic_error_t supplied
 *
 * Returns the reply of the request asked by
 *
 * The parameter @p e supplied to this function must be NULL if
 * xcb_xf86dri_auth_connection_unchecked(). is used.
 * Otherwise, it stores the error if any.
 *
 * The returned value must be freed by the caller using free().
 */
xcb_xf86dri_auth_connection_reply_t *
xcb_xf86dri_auth_connection_reply (xcb_connection_t                      *c,
                                   xcb_xf86dri_auth_connection_cookie_t   cookie  /**< */,
                                   xcb_generic_error_t                  **e);


#ifdef __cplusplus
}
#endif

#endif

/**
 * @}
 */
