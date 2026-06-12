add_library(picoboot_connection_header INTERFACE)
target_include_directories(picoboot_connection_header INTERFACE ${CMAKE_CURRENT_LIST_DIR})

add_library(picoboot_connection INTERFACE)

target_sources(picoboot_connection INTERFACE
        ${CMAKE_CURRENT_LIST_DIR}/picoboot_connection.c)

target_link_libraries(picoboot_connection INTERFACE picoboot_connection_header)

# Select the USB transport backend.
if (USE_TINYUSB)
    # On-device (TinyUSB) build
    target_sources(picoboot_connection INTERFACE
            ${CMAKE_CURRENT_LIST_DIR}/usb_transport_tinyusb.c)
else()
    # Desktop (libusb) build
    target_sources(picoboot_connection INTERFACE
            ${CMAKE_CURRENT_LIST_DIR}/usb_transport_libusb.c)
endif()

add_library(picoboot_connection_cxx INTERFACE)
target_sources(picoboot_connection_cxx INTERFACE
        ${CMAKE_CURRENT_LIST_DIR}/picoboot_connection_cxx.cpp)

target_link_libraries(picoboot_connection_cxx INTERFACE picoboot_connection)
