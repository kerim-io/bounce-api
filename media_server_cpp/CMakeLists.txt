cmake_minimum_required(VERSION 3.15)
project(BitBaselMediaServer)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Find required packages
find_package(Threads REQUIRED)
find_package(Boost REQUIRED COMPONENTS system thread)

# WebRTC library (you'll need to build libwebrtc separately)
# Download from: https://webrtc.googlesource.com/src
# Or use pre-built binaries
set(WEBRTC_ROOT "${CMAKE_SOURCE_DIR}/third_party/webrtc" CACHE PATH "WebRTC root directory")
set(WEBRTC_INCLUDE_DIR "${WEBRTC_ROOT}/include")
set(WEBRTC_LIB_DIR "${WEBRTC_ROOT}/lib")

# Include directories
include_directories(
    ${CMAKE_SOURCE_DIR}/include
    ${WEBRTC_INCLUDE_DIR}
    ${Boost_INCLUDE_DIRS}
)

# Link directories
link_directories(
    ${WEBRTC_LIB_DIR}
)

# Source files
set(SOURCES
    src/main.cpp
    src/streaming_server.cpp
    src/webrtc_handler.cpp
    src/room_manager.cpp
    src/http_server.cpp
    src/config.cpp
)

# Header files
set(HEADERS
    include/streaming_server.h
    include/webrtc_handler.h
    include/room_manager.h
    include/http_server.h
    include/config.h
)

# Create executable
add_executable(media_server ${SOURCES} ${HEADERS})

# Link libraries
target_link_libraries(media_server
    ${CMAKE_THREAD_LIBS_INIT}
    ${Boost_LIBRARIES}
    # WebRTC libraries (these names may vary based on your build)
    # webrtc
    # Comment: Full WebRTC linking is complex and depends on how you built it
    # You may need to link many individual components
)

# Compiler flags
if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
    target_compile_options(media_server PRIVATE
        -Wall -Wextra -Wpedantic
        -O2  # Optimization for release
    )
endif()

# Installation
install(TARGETS media_server DESTINATION bin)

# Copy config file
configure_file(
    ${CMAKE_SOURCE_DIR}/config.json
    ${CMAKE_BINARY_DIR}/config.json
    COPYONLY
)