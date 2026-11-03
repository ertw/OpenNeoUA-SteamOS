# Small, asset-free regressions. World probes that need a full game installation
# remain in world/tests; do not silently run them against a developer's saves.
function(openneoua_test name)
    add_executable(test_${name} ${ARGN})
    target_include_directories(test_${name} PRIVATE ${PROJECT_SOURCE_DIR})
    add_test(NAME ${name} COMMAND test_${name})
    set_tests_properties(${name} PROPERTIES TIMEOUT 30)
endfunction()

openneoua_test(gamepad_input test_gamepad_input.cpp)
target_compile_definitions(test_gamepad_input PRIVATE SDL_MAIN_HANDLED)
target_link_libraries(test_gamepad_input PRIVATE PkgConfig::SDL2)

# Test the portable state machine and disabled backend without a live system bus.
openneoua_test(sleep_notifications test_sleep_notifications.cpp ../system/sleepnotify.cpp)

# These upstream math/clock regressions also need no game data or renderer.
openneoua_test(debug_time_scale ../world/tests/debug_time_scale_test.cpp ../system/gametime.cpp)
openneoua_test(ground_decal_sphere ../world/tests/ground_decal_sphere_test.cpp)

if(UNIX AND CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
    # Link the production helpers, discarding unrelated engine/GUI functions.
    # Both filesystem suites use ASan to catch iterator invalidation regressions.
    add_library(test_filesystem_support STATIC
        ../common/env.cpp
        ../common/utils.cpp
        ../system/fsmgr.cpp
    )
    target_include_directories(test_filesystem_support PUBLIC
        ${PROJECT_SOURCE_DIR} ${LUA_INCLUDE_DIR} ${OPENAL_INCLUDE_DIR} ${SDL2_INCLUDE_DIRS}
    )
    target_compile_options(test_filesystem_support PRIVATE -ffunction-sections -fdata-sections)
    target_compile_options(test_filesystem_support PUBLIC -fsanitize=address -fno-omit-frame-pointer)
    # The engine headers mention SDL types, but these helpers do not call SDL.
    target_link_libraries(test_filesystem_support PUBLIC -fsanitize=address)
    if(APPLE)
        target_link_libraries(test_filesystem_support PUBLIC -Wl,-dead_strip)
    else()
        target_link_libraries(test_filesystem_support PUBLIC -Wl,--gc-sections)
    endif()
    foreach(name data_paths overlay_mutation)
        openneoua_test(${name} test_${name}.cpp)
        target_link_libraries(test_${name} PRIVATE test_filesystem_support)
        set_tests_properties(${name} PROPERTIES
            ENVIRONMENT "ASAN_OPTIONS=detect_leaks=0:halt_on_error=1:abort_on_error=1"
        )
    endforeach()
endif()
