add_library(elf STATIC
        elf_file.cpp
        crc32.cpp
        )

target_include_directories(elf PUBLIC ${CMAKE_CURRENT_LIST_DIR})

target_link_libraries(elf PUBLIC model errors)
